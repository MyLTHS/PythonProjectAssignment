from django.utils import timezone
from rest_framework import serializers

from .models import ActivityLog, FileItem, Folder, Label, ShareLink
from .upload_policy import (
    ALLOWED_EXTENSIONS,
    BLOCKED_EXTENSIONS,
    MAX_UPLOAD_SIZE,
)


class FolderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Folder
        fields = [
            "id",
            "name",
            "parent",
            "is_deleted",
            "deleted_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "is_deleted",
            "deleted_at",
            "created_at",
            "updated_at",
        ]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Folder name cannot be empty.")
        return value

    def validate(self, attrs):
        request = self.context.get("request")
        request_user = request.user if request else None
        owner = self.instance.owner if self.instance else request_user
        parent = attrs.get(
            "parent",
            self.instance.parent if self.instance else None,
        )

        if not request_user:
            raise serializers.ValidationError("Authenticated user is required.")

        if self.instance and self.instance.owner != request_user and not request_user.is_staff:
            raise serializers.ValidationError("You cannot edit this folder.")

        if parent and parent.owner != owner:
            raise serializers.ValidationError(
                {"parent": "Parent folder must belong to the same owner."}
            )

        if parent and parent.is_deleted:
            raise serializers.ValidationError(
                {"parent": "Cannot place folder inside a deleted parent."}
            )

        ancestor = parent
        while self.instance and ancestor:
            if ancestor == self.instance:
                raise serializers.ValidationError(
                    {"parent": "A folder cannot be inside itself."}
                )
            ancestor = ancestor.parent

        name = attrs.get("name", self.instance.name if self.instance else None)
        duplicate_qs = Folder.objects.filter(
            owner=owner,
            parent=parent,
            name=name,
        )

        if self.instance:
            duplicate_qs = duplicate_qs.exclude(pk=self.instance.pk)

        if name and duplicate_qs.exists():
            raise serializers.ValidationError(
                {"name": "A folder with this name already exists in the same parent."}
            )

        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        return Folder.objects.create(owner=request.user, **validated_data)


class FileListSerializer(serializers.ModelSerializer):
    folder_name = serializers.CharField(source="folder.name", read_only=True)
    owner_username = serializers.CharField(source="owner.username", read_only=True)
    labels = serializers.StringRelatedField(many=True, read_only=True)

    class Meta:
        model = FileItem
        fields = [
            "id",
            "name",
            "folder_name",
            "owner_username",
            "external_url",
            "mime_type",
            "size_bytes",
            "description",
            "status",
            "is_starred",
            "download_count",
            "labels",
            "created_at",
            "updated_at",
        ]


class FileUploadSerializer(serializers.ModelSerializer):
    folder_id = serializers.PrimaryKeyRelatedField(
        queryset=Folder.objects.all(),
        source="folder",
        required=False,
        allow_null=True,
    )
    labels = serializers.PrimaryKeyRelatedField(
        queryset=Label.objects.all(),
        many=True,
        required=False,
    )

    class Meta:
        model = FileItem
        fields = [
            "id",
            "file",
            "external_url",
            "name",
            "folder_id",
            "description",
            "labels",
            "size_bytes",
            "mime_type",
            "status",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "name",
            "size_bytes",
            "mime_type",
            "status",
            "created_at",
        ]

    def validate_file(self, value):
        if value.size > MAX_UPLOAD_SIZE:
            raise serializers.ValidationError("File vượt quá 20MB.")

        file_name = value.name.lower()

        for ext in BLOCKED_EXTENSIONS:
            if file_name.endswith(ext):
                raise serializers.ValidationError(
                    "Định dạng file này không được phép."
                )

        if not any(file_name.endswith(ext) for ext in ALLOWED_EXTENSIONS):
            raise serializers.ValidationError("Định dạng file không hợp lệ.")

        return value

    def validate(self, attrs):
        request = self.context.get("request")
        owner = request.user if request else None
        folder = attrs.get("folder")

        if not owner:
            raise serializers.ValidationError("Authenticated user is required.")

        if not hasattr(owner, "profile"):
            raise serializers.ValidationError("User profile does not exist.")

        profile = owner.profile
        if profile.is_suspended:
            raise serializers.ValidationError("Your account is suspended.")

        upload_file = attrs.get("file")
        external_url = attrs.get("external_url")
        if not upload_file and not external_url:
            raise serializers.ValidationError(
                {"file": "Provide either a file upload or an external URL."}
            )
        if upload_file and external_url:
            raise serializers.ValidationError(
                {"external_url": "Choose either a file upload or an external URL."}
            )

        if upload_file and not profile.can_upload(upload_file.size):
            raise serializers.ValidationError("You do not have enough storage quota.")

        if folder and folder.owner != owner:
            raise serializers.ValidationError(
                {"folder_id": "Folder không thuộc quyền sở hữu của bạn."}
            )

        if folder and folder.is_deleted:
            raise serializers.ValidationError(
                {"folder_id": "Không thể upload vào folder đang ở trash."}
            )

        return attrs

    def create(self, validated_data):
        labels = validated_data.pop("labels", [])
        request = self.context["request"]

        file_item = FileItem.objects.create(
            owner=request.user,
            status=(
                FileItem.STATUS_READY
                if validated_data.get("external_url")
                else FileItem.STATUS_PROCESSING
            ),
            **validated_data,
        )

        if labels:
            file_item.labels.set(labels)

        return file_item


class FileUpdateSerializer(serializers.ModelSerializer):
    folder_id = serializers.PrimaryKeyRelatedField(
        queryset=Folder.objects.all(),
        source="folder",
        required=False,
        allow_null=True,
    )
    labels = serializers.PrimaryKeyRelatedField(
        queryset=Label.objects.all(),
        many=True,
        required=False,
    )

    class Meta:
        model = FileItem
        fields = ["name", "folder_id", "description", "labels", "is_starred"]

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("File name cannot be empty.")
        return value

    def validate(self, attrs):
        request = self.context.get("request")
        request_user = request.user if request else None
        folder = attrs.get("folder", self.instance.folder if self.instance else None)

        if not request_user:
            raise serializers.ValidationError("Authenticated user is required.")

        if not self.instance:
            raise serializers.ValidationError(
                "This serializer is only for updating files."
            )

        if self.instance.owner != request_user and not request_user.is_staff:
            raise serializers.ValidationError(
                "You cannot edit a file that does not belong to you."
            )

        if self.instance.is_deleted:
            raise serializers.ValidationError(
                "Cannot edit metadata of a file in trash."
            )

        if folder and folder.owner != self.instance.owner:
            raise serializers.ValidationError(
                {"folder_id": "Folder must belong to the same owner."}
            )

        if folder and folder.is_deleted:
            raise serializers.ValidationError(
                {"folder_id": "Cannot move file into a deleted folder."}
            )

        return attrs


class ShareLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShareLink
        fields = [
            "id",
            "file",
            "token",
            "permission",
            "recipient_email",
            "is_active",
            "expires_at",
            "view_count",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "token",
            "is_active",
            "view_count",
            "created_at",
        ]

    def validate(self, attrs):
        request = self.context.get("request")
        owner = request.user if request else None
        file_item = attrs.get("file")

        if not owner:
            raise serializers.ValidationError("Authenticated user is required.")

        if not file_item:
            raise serializers.ValidationError({"file": "File is required."})

        if file_item.owner != owner:
            raise serializers.ValidationError(
                {"file": "You can only share your own file."}
            )

        if file_item.is_deleted:
            raise serializers.ValidationError(
                {"file": "Cannot share a file that is in trash."}
            )

        if file_item.status in {
            FileItem.STATUS_INFECTED,
            FileItem.STATUS_BLOCKED,
        }:
            raise serializers.ValidationError(
                {"file": "Cannot share a file that is infected or blocked."}
            )

        expires_at = attrs.get("expires_at")
        if expires_at and expires_at <= timezone.now():
            raise serializers.ValidationError(
                {"expires_at": "Expiration time must be in the future."}
            )

        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        return ShareLink.objects.create(created_by=request.user, **validated_data)


class ActivityLogSerializer(serializers.ModelSerializer):
    user_username = serializers.CharField(source="user.username", read_only=True)
    file_name = serializers.CharField(source="file.name", read_only=True)
    folder_name = serializers.CharField(source="folder.name", read_only=True)

    class Meta:
        model = ActivityLog
        fields = [
            "id",
            "user_username",
            "action",
            "file_name",
            "folder_name",
            "detail",
            "created_at",
        ]
