from rest_framework.permissions import BasePermission

from .models import FileItem, ShareLink


class IsOwnerOrStaff(BasePermission):
    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False
        return request.user.is_staff or obj.owner == request.user


class _SharedFilePermission(BasePermission):
    required_permission = None

    def has_object_permission(self, request, view, obj):
        if not isinstance(obj, FileItem):
            return False

        if obj.is_deleted or obj.status in {
            FileItem.STATUS_INFECTED,
            FileItem.STATUS_BLOCKED,
        }:
            return False

        if request.user.is_authenticated and (
            request.user.is_staff or obj.owner == request.user
        ):
            return True

        token = request.query_params.get("token")
        if not token:
            return False

        try:
            share_link = obj.share_links.get(token=token)
        except ShareLink.DoesNotExist:
            return False

        if not share_link.is_valid:
            return False

        return (
            self.required_permission is None
            or share_link.permission == self.required_permission
        )


class CanViewFile(_SharedFilePermission):
    pass


class CanDownloadFile(_SharedFilePermission):
    required_permission = ShareLink.PERMISSION_DOWNLOAD
