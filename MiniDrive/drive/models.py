import mimetypes
import uuid
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class Profile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    contact_email = models.EmailField(blank=True)
    storage_quota_gb = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("5.00"),
    )
    used_storage_bytes = models.PositiveBigIntegerField(default=0)
    is_suspended = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile of {self.user.username}"

    @property
    def quota_bytes(self):
        return int(self.storage_quota_gb * 1024 * 1024 * 1024)

    @property
    def remaining_storage_bytes(self):
        return max(0, self.quota_bytes - self.used_storage_bytes)

    def can_upload(self, file_size_bytes):
        return (
            not self.is_suspended
            and self.used_storage_bytes + file_size_bytes <= self.quota_bytes
        )


class Label(models.Model):
    name = models.CharField(max_length=40, unique=True)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    color = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return self.name

    def clean(self):
        if not self.name.strip():
            raise ValidationError({"name": "Label name cannot be empty."})

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        self.full_clean()
        super().save(*args, **kwargs)


class Folder(models.Model):
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="folders",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="children",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=40)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def clean(self):
        if not self.name.strip():
            raise ValidationError({"name": "Folder name cannot be empty."})

        if self.parent and self.parent == self:
            raise ValidationError({"parent": "A folder cannot be its own parent."})

        if self.parent and self.parent.owner != self.owner:
            raise ValidationError(
                {"parent": "Parent folder must belong to the same owner."}
            )

        if self.parent and self.parent.is_deleted:
            raise ValidationError(
                {"parent": "Cannot place folder inside a deleted parent."}
            )

        duplicate_qs = Folder.objects.filter(
            owner=self.owner,
            parent=self.parent,
            name=self.name,
        )
        if self.pk:
            duplicate_qs = duplicate_qs.exclude(pk=self.pk)

        if duplicate_qs.exists():
            raise ValidationError(
                {"name": "A folder with this name already exists in the same parent."}
            )

    def save(self, *args, **kwargs):
        if self.is_deleted and self.deleted_at is None:
            self.deleted_at = timezone.now()
        if not self.is_deleted:
            self.deleted_at = None

        self.full_clean()
        super().save(*args, **kwargs)

#không hiểu cần phải đọc và tìm hiểu các phần này
class FileItem(models.Model):
    STATUS_PROCESSING = "processing"
    STATUS_READY = "ready"
    STATUS_INFECTED = "infected"
    STATUS_BLOCKED = "blocked"
    STATUS_CHOICES = [
        (STATUS_PROCESSING, "Processing"),
        (STATUS_READY, "Ready"),
        (STATUS_INFECTED, "Infected"),
        (STATUS_BLOCKED, "Blocked"),
    ]

    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="files",
    )
    folder = models.ForeignKey(
        Folder,
        on_delete=models.CASCADE,
        related_name="files",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    file = models.FileField(upload_to="uploads/%Y/%m/", null=True, blank=True)
    external_url = models.URLField(blank=True)
    description = models.TextField(blank=True)
    mime_type = models.CharField(max_length=255, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    is_starred = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PROCESSING,
    )
    download_count = models.PositiveIntegerField(default=0)
    labels = models.ManyToManyField(Label, related_name="files", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def clean(self):
        if not self.file and not self.external_url:
            raise ValidationError(
                {"file": "A file upload or external URL is required."}
            )

        if self.file and self.external_url:
            raise ValidationError(
                {"external_url": "Choose either an uploaded file or an external URL."}
            )

        if self.folder and self.folder.owner != self.owner:
            raise ValidationError(
                {"folder": "The selected folder must belong to the same owner."}
            )

        if self.folder and self.folder.is_deleted:
            raise ValidationError(
                {"folder": "Cannot place a file inside a deleted folder."}
            )

        if self.size_bytes < 0:
            raise ValidationError({"size_bytes": "File size cannot be negative."})

        if self.is_deleted and self.deleted_at is None:
            raise ValidationError(
                {"deleted_at": "deleted_at is required when a file is deleted."}
            )

        if not self.is_deleted and self.deleted_at is not None:
            raise ValidationError(
                {"deleted_at": "deleted_at must be empty when a file is active."}
            )

    def save(self, *args, **kwargs):
        if self.file:
            if not self.name:
                self.name = self.file.name.split("/")[-1]

            self.size_bytes = self.file.size or 0

            guessed_mime_type, _ = mimetypes.guess_type(self.file.name)
            if guessed_mime_type:
                self.mime_type = guessed_mime_type
        elif self.external_url and not self.name:
            self.name = self.external_url

        if self.is_deleted and self.deleted_at is None:
            self.deleted_at = timezone.now()
        if not self.is_deleted:
            self.deleted_at = None

        self.full_clean()
        super().save(*args, **kwargs)


class ShareLink(models.Model):
    PERMISSION_VIEW = "view"
    PERMISSION_DOWNLOAD = "download"
    PERMISSION_CHOICES = [
        (PERMISSION_VIEW, "View"),
        (PERMISSION_DOWNLOAD, "Download"),
    ]

    file = models.ForeignKey(
        FileItem,
        on_delete=models.CASCADE,
        related_name="share_links",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="created_share_links",
    )
    token = models.CharField(max_length=64, unique=True, blank=True)
    permission = models.CharField(
        max_length=20,
        choices=PERMISSION_CHOICES,
        default=PERMISSION_VIEW,
    )
    recipient_email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    view_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.file.name} - {self.permission}"

    @property
    def is_expired(self):
        return self.expires_at is not None and self.expires_at <= timezone.now()

    @property
    def is_valid(self):
        return self.is_active and not self.is_expired

    def clean(self):
        if self.file.is_deleted:
            raise ValidationError({"file": "Cannot share a file that is in trash."})

        if self.file.status in {
            FileItem.STATUS_INFECTED,
            FileItem.STATUS_BLOCKED,
        }:
            raise ValidationError(
                {"file": "Cannot share a file that is infected or blocked."}
            )

        if self.created_by != self.file.owner:
            raise ValidationError(
                {"created_by": "Only the file owner can create a share link."}
            )

        if self.expires_at and self.expires_at <= timezone.now():
            raise ValidationError(
                {"expires_at": "Expiration time must be in the future."}
            )

    def save(self, *args, **kwargs):
        if not self.token:
            token = uuid.uuid4().hex
            while ShareLink.objects.filter(token=token).exists():
                token = uuid.uuid4().hex
            self.token = token

        self.full_clean()
        super().save(*args, **kwargs)


class ActivityLog(models.Model):
    ACTION_UPLOAD = "upload"
    ACTION_DELETE = "delete"
    ACTION_RESTORE = "restore"
    ACTION_SHARE = "share"
    ACTION_MOVE = "move"
    ACTION_SCAN = "scan"
    ACTION_EXPIRE = "expire"
    ACTION_PURGE = "purge"
    ACTION_CHOICES = [
        (ACTION_UPLOAD, "Upload"),
        (ACTION_DELETE, "Delete"),
        (ACTION_RESTORE, "Restore"),
        (ACTION_SHARE, "Share"),
        (ACTION_MOVE, "Move"),
        (ACTION_SCAN, "Scan"),
        (ACTION_EXPIRE, "Expire"),
        (ACTION_PURGE, "Purge"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="activity_logs",
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    file = models.ForeignKey(
        FileItem,
        on_delete=models.SET_NULL,
        related_name="activity_logs",
        null=True,
        blank=True,
    )
    folder = models.ForeignKey(
        Folder,
        on_delete=models.SET_NULL,
        related_name="activity_logs",
        null=True,
        blank=True,
    )
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.action} at {self.created_at:%Y-%m-%d %H:%M:%S}"


class FileShare(models.Model):
    PERMISSION_VIEWER = "viewer"
    PERMISSION_EDITOR = "editor"
    PERMISSION_CHOICES = [
        (PERMISSION_VIEWER, "Viewer"),
        (PERMISSION_EDITOR, "Editor"),
    ]

    file = models.ForeignKey(
        FileItem,
        on_delete=models.CASCADE,
        related_name="direct_shares",
    )
    shared_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="sent_file_shares",
    )
    shared_with = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="received_file_shares",
    )
    permission = models.CharField(
        max_length=20,
        choices=PERMISSION_CHOICES,
        default=PERMISSION_VIEWER,
    )
    accepted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.file.name} -> {self.shared_with.username}"

    def clean(self):
        if self.shared_by != self.file.owner:
            raise ValidationError(
                {"shared_by": "Only the file owner can directly share the file."}
            )

        if self.file.is_deleted:
            raise ValidationError({"file": "Cannot share a file that is in trash."})

        if self.shared_with == self.shared_by:
            raise ValidationError(
                {"shared_with": "shared_with must be different from shared_by."}
            )
