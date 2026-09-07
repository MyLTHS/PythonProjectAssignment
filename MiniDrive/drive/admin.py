from django.contrib import admin
from django.db.models import Q, Sum
from django.utils import timezone

from .models import Profile, Label, Folder, FileItem, ShareLink, ActivityLog, FileShare


def get_folder_tree_ids(queryset):
    folder_ids = list(queryset.values_list("id", flat=True))
    all_ids = set(folder_ids)
    pending_ids = folder_ids
    while pending_ids:
        pending_ids = list(
            Folder.objects.filter(parent_id__in=pending_ids).values_list(
                "id", flat=True
            )
        )
        all_ids.update(pending_ids)
    return all_ids


def recalculate_storage_for_users(user_ids):
    profiles = list(Profile.objects.filter(user_id__in=user_ids))
    for profile in profiles:
        profile.used_storage_bytes = (
            FileItem.objects.active()
            .filter(owner_id=profile.user_id)
            .aggregate(total=Sum("size_bytes"))["total"]
            or 0
        )
    Profile.objects.bulk_update(profiles, ["used_storage_bytes"])


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "used_storage_bytes", "storage_quota_gb", "is_suspended")
    list_filter = ("is_suspended",)
    search_fields = ("user__username", "contact_email")
    readonly_fields = ("used_storage_bytes", "created_at", "updated_at")

    @admin.action(description="Recalculate selected users' storage")
    def recalculate_storage(self, request, queryset):
        recalculate_storage_for_users(queryset.values_list("user_id", flat=True))

    actions = ("recalculate_storage",)


@admin.register(Label)
class LabelAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "color")
    search_fields = ("name",)


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "parent", "is_deleted", "created_at")
    list_filter = ("is_deleted",)
    search_fields = ("name", "owner__username")

    @admin.action(description="Move selected folders to trash")
    def soft_delete_folders(self, request, queryset):
        user_ids = list(queryset.values_list("owner_id", flat=True).distinct())
        folder_ids = get_folder_tree_ids(queryset)
        deleted_at = timezone.now()
        files = FileItem.objects.filter(folder_id__in=folder_ids, is_deleted=False)
        Folder.objects.filter(id__in=folder_ids).update(
            is_deleted=True, deleted_at=deleted_at
        )
        files.update(is_deleted=True, deleted_at=deleted_at)
        recalculate_storage_for_users(user_ids)

    @admin.action(description="Restore selected folders")
    def restore_folders(self, request, queryset):
        restorable_ids = [
            folder.id
            for folder in queryset.select_related("parent")
            if folder.parent is None or not folder.parent.is_deleted
        ]
        folders = Folder.objects.filter(id__in=restorable_ids)
        user_ids = list(folders.values_list("owner_id", flat=True).distinct())
        folder_ids = get_folder_tree_ids(folders)
        Folder.objects.filter(id__in=folder_ids).update(
            is_deleted=False, deleted_at=None
        )
        FileItem.objects.filter(folder_id__in=folder_ids, is_deleted=True).update(
            is_deleted=False, deleted_at=None
        )
        recalculate_storage_for_users(user_ids)

    actions = ("soft_delete_folders", "restore_folders")


@admin.register(FileItem)
class FileItemAdmin(admin.ModelAdmin):
    list_display = (
        "name", "owner", "folder", "size_bytes", "status", "is_starred",
        "is_deleted", "created_at",
    )
    list_filter = ("status", "is_deleted", "is_starred", "mime_type", "labels")
    search_fields = ("name", "owner__username", "description", "labels__name")
    readonly_fields = ("mime_type", "size_bytes", "download_count", "created_at", "updated_at")
    fieldsets = (
        ("File", {"fields": ("owner", "folder", "name", "file", "external_url")}),
        ("Metadata", {"fields": ("description", "mime_type", "size_bytes", "labels")}),
        ("State", {"fields": ("status", "is_starred", "is_deleted", "deleted_at")}),
        ("Audit", {"fields": ("download_count", "created_at", "updated_at")}),
    )

    @admin.action(description="Move selected files to trash")
    def soft_delete_files(self, request, queryset):
        user_ids = list(queryset.values_list("owner_id", flat=True).distinct())
        queryset.update(is_deleted=True, deleted_at=timezone.now())
        recalculate_storage_for_users(user_ids)

    @admin.action(description="Restore selected files")
    def restore_files(self, request, queryset):
        queryset = queryset.filter(
            Q(folder__isnull=True) | Q(folder__is_deleted=False)
        )
        user_ids = list(queryset.values_list("owner_id", flat=True).distinct())
        queryset.update(is_deleted=False, deleted_at=None)
        recalculate_storage_for_users(user_ids)

    @admin.action(description="Mark selected files as blocked")
    def mark_blocked(self, request, queryset):
        queryset.update(status=FileItem.STATUS_BLOCKED)

    @admin.action(description="Mark selected files as ready")
    def mark_ready(self, request, queryset):
        queryset.update(status=FileItem.STATUS_READY)

    actions = ("soft_delete_files", "restore_files", "mark_blocked", "mark_ready")


@admin.register(ShareLink)
class ShareLinkAdmin(admin.ModelAdmin):
    list_display = ("file", "created_by", "permission", "is_active", "expires_at")
    list_filter = ("permission", "is_active")
    search_fields = ("file__name", "created_by__username", "token")
    readonly_fields = ("token", "view_count", "created_at")

    @admin.action(description="Deactivate selected links")
    def deactivate_links(self, request, queryset):
        queryset.update(is_active=False)

    @admin.action(description="Activate selected links")
    def activate_links(self, request, queryset):
        queryset.update(is_active=True)

    actions = ("deactivate_links", "activate_links")


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("action", "user", "file", "folder", "created_at")
    list_filter = ("action",)
    search_fields = ("user__username", "file__name", "detail")
    readonly_fields = ("user", "action", "file", "folder", "detail", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FileShare)
class FileShareAdmin(admin.ModelAdmin):
    list_display = ("file", "shared_by", "shared_with", "permission", "accepted")
    list_filter = ("permission", "accepted")
    search_fields = ("file__name", "shared_by__username", "shared_with__username")
