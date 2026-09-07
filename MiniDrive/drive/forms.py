from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from . import models
from .models import FileItem, Folder, Label


class FolderChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, folder):
        return folder.path


class FolderForm(forms.ModelForm):
    parent = FolderChoiceField(
        queryset=Folder.objects.none(),
        required=False,
        empty_label="Root",
    )

    class Meta:
        model = models.Folder
        fields = ["name", "parent"]

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner

        if owner:
            folders = Folder.objects.filter(
                owner=owner,
                is_deleted=False,
            ).order_by("name")

            if self.instance.pk:
                excluded_ids = {self.instance.pk}
                pending_ids = [self.instance.pk]
                while pending_ids:
                    pending_ids = list(
                        Folder.objects.filter(parent_id__in=pending_ids).values_list(
                            "pk", flat=True
                        )
                    )
                    excluded_ids.update(pending_ids)
                folders = folders.exclude(pk__in=excluded_ids)

            self.fields["parent"].queryset = folders

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("Please enter a name.")
        return name

    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get("name")
        parent = cleaned_data.get("parent")
        if not self.owner:
            raise ValidationError("Owner is required.")
        if parent and parent.owner != self.owner:
            self.add_error("parent", "Parent folder must belong to the same owner.")

        if parent and parent.is_deleted:
            self.add_error("parent", "Cannot place folder inside a deleted parent.")

        if self.instance.pk and parent == self.instance:
            self.add_error("parent", "A folder cannot be its own parent.")

        duplicate_qs = Folder.objects.filter(
            owner=self.owner,
            parent=parent,
            name=name,
        )

        if self.instance.pk:
            duplicate_qs = duplicate_qs.exclude(pk=self.instance.pk)

        if name and duplicate_qs.exists():
            self.add_error(
                "name",
                "A folder with this name already exists in the same parent.",
            )

        return cleaned_data


class FileMetadataForm(forms.ModelForm):
    folder = FolderChoiceField(
        queryset=Folder.objects.none(),
        required=False,
        empty_label="Root",
    )

    class Meta:
        model = models.FileItem
        fields = ["name", "folder", "description", "labels"]

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner

        if owner:
            self.fields["folder"].queryset = Folder.objects.filter(
                owner=owner,
                is_deleted=False,
            )
        self.fields["labels"].queryset = Label.objects.all().order_by("name")

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("Please enter a name.")
        return name

    def clean(self):
        cleaned_data = super().clean()
        folder = cleaned_data.get("folder")

        if not self.owner:
            raise ValidationError("Owner is required.")

        if not self.instance.pk:
            raise ValidationError("This form is only for updating an existing file.")

        if self.instance.is_deleted:
            raise ValidationError("Cannot edit metadata of a file in trash.")
        if self.instance.owner != self.owner:
            raise ValidationError("You cannot edit a file that does not belong to you.")
        if folder and folder.owner != self.owner:
            self.add_error("folder", "Parent folder must belong to the same owner.")

        if folder and folder.is_deleted:
            self.add_error("folder", "Cannot move file into a deleted folder.")

        return cleaned_data


class ShareLinkForm(forms.ModelForm):
    class Meta:
        model = models.ShareLink
        fields = ["permission", "recipient_email", "expires_at"]

    def __init__(self, *args, file_item=None, created_by=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.file_item = file_item
        self.created_by = created_by
        if file_item:
            self.instance.file = file_item
        if created_by:
            self.instance.created_by = created_by

    def clean(self):
        cleaned_data = super().clean()
        expires_at = cleaned_data.get("expires_at")

        if not self.file_item:
            raise ValidationError("File item is required.")

        if not self.created_by:
            raise ValidationError("Created by is required.")

        if self.file_item.owner != self.created_by:
            raise ValidationError("Only the file owner can create a share link.")

        if self.file_item.is_deleted:
            raise ValidationError("Cannot share a file that is in trash.")

        if self.file_item.status in {
            FileItem.STATUS_INFECTED,
            FileItem.STATUS_BLOCKED,
        }:
            raise ValidationError("Cannot share a file that is infected or blocked.")

        if expires_at and expires_at <= timezone.now():
            self.add_error("expires_at", "Expiration time must be in the future.")

        return cleaned_data
