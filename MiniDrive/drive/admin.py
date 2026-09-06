from django.contrib import admin

from .models import Profile, Label, Folder, FileItem, ShareLink, ActivityLog, FileShare


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "used_storage_bytes", "storage_quota_gb", "is_suspended")
    list_filter = ("is_suspended",)
    search_fields = ("user__username", "contact_email")


@admin.register(Label)
class LabelAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "color")
    search_fields = ("name",)


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "parent", "is_deleted", "created_at")
    list_filter = ("is_deleted",)
    search_fields = ("name", "owner__username")


@admin.register(FileItem)
class FileItemAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "folder", "status", "size_bytes", "is_deleted")
    list_filter = ("status", "is_deleted", "is_starred")
    search_fields = ("name", "owner__username", "description")
    readonly_fields = ("mime_type", "size_bytes", "download_count", "created_at", "updated_at")

    @admin.action(description="Mark selected files as blocked")
    def mark_as_blocked(self, request, queryset):
        queryset.update(status=FileItem.STATUS_BLOCKED)

    actions = ("mark_as_blocked",)


@admin.register(ShareLink)
class ShareLinkAdmin(admin.ModelAdmin):
    list_display = ("file", "created_by", "permission", "is_active", "expires_at")
    list_filter = ("permission", "is_active")
    search_fields = ("file__name", "created_by__username", "token")
    readonly_fields = ("token", "view_count", "created_at")


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
