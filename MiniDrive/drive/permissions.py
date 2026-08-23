from rest_framework.permissions import BasePermission
from .models import FileItem, ShareLink


class IsOwnerOrStaff(BasePermission):
    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        if request.user.is_staff:
            return True

        if obj.owner == request.user:
            return True

        return False



class CanViewFile(BasePermission):
    def has_object_permission(self, request, view, obj):
        if not isinstance(obj, FileItem):
            return False

        if obj.is_deleted:
            return False

        if obj.status in [FileItem.STATUS_INFECTED, FileItem.STATUS_BLOCKED]:
            return False

        if request.user.is_authenticated:
            if request.user.is_staff:
                return True

            if obj.owner == request.user:
                return True

        token = request.query_params.get("token")

        if not token:
            return False

        try:
            share_link = obj.share_links.get(token=token)
        except ShareLink.DoesNotExist:
            return False

        if share_link.is_valid:
            return True

        return False





class CanDownloadFile(BasePermission):
    def has_object_permission(self, request, view, obj):
        if not isinstance(obj, FileItem):
            return False

        if obj.is_deleted:
            return False

        if obj.status in [FileItem.STATUS_INFECTED, FileItem.STATUS_BLOCKED]:
            return False

        if request.user.is_authenticated:
            if request.user.is_staff:
                return True

            if obj.owner == request.user:
                return True

        token = request.query_params.get("token")
        if not token:
            return False

        try:
            share_link = obj.share_links.get(token=token)
        except ShareLink.DoesNotExist:
            return False

        if share_link.is_valid and share_link.permission == ShareLink.PERMISSION_DOWNLOAD:
            return True

        return False