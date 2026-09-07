from django.contrib.auth import authenticate, logout as django_logout
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import F, Sum
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView
from rest_framework import generics, status
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .forms import FileMetadataForm, FolderForm, ShareLinkForm
from .models import ActivityLog, FileItem, Folder, Profile, ShareLink
from .permissions import CanDownloadFile, CanViewFile, IsOwnerOrStaff
from .serializers import (
    ActivityLogSerializer,
    FileListSerializer,
    FileUpdateSerializer,
    FileUploadSerializer,
    FolderSerializer,
    ShareLinkSerializer,
)
from .tasks import scan_uploaded_file


def folder_tree_ids(folder):
    ids = [folder.pk]
    pending = [folder.pk]
    while pending:
        children = list(
            Folder.objects.filter(parent_id__in=pending).values_list("id", flat=True)
        )
        ids.extend(children)
        pending = children
    return ids


class LoginAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get("username", "").strip()
        password = request.data.get("password", "")

        if not username or not password:
            return Response(
                {"detail": "Username and password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request=request, username=username, password=password)
        if user is None:
            return Response(
                {"detail": "Invalid username or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        token, _ = Token.objects.get_or_create(user=user)
        Profile.objects.get_or_create(user=user)

        return Response(
            {
                "token": token.key,
                "token_type": "Bearer",
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                },
            }
        )


class LogoutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.auth:
            request.auth.delete()
        else:
            Token.objects.filter(user=request.user).delete()
        django_logout(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ActivityLogListAPIView(generics.ListAPIView):
    serializer_class = ActivityLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            ActivityLog.objects.filter(user=self.request.user)
            .select_related("user", "file", "folder")
            .order_by("-created_at")
        )


class StaffActivityLogListAPIView(generics.ListAPIView):
    serializer_class = ActivityLogSerializer
    permission_classes = [IsAdminUser]

    def get_queryset(self):
        return (
            ActivityLog.objects.select_related("user", "file", "folder")
            .all()
            .order_by("-created_at")
        )


class StaffReportAPIView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        storage_by_user = list(FileItem.objects.storage_summary_by_user())
        file_types = list(FileItem.objects.file_type_summary())
        top_labels = [
            {
                "id": label.id,
                "name": label.name,
                "file_count": label.file_count,
            }
            for label in FileItem.objects.top_labels()
        ]

        return Response(
            {
                "total_users": User.objects.count(),
                "total_files": FileItem.objects.active().count(),
                "total_storage": (
                    FileItem.objects.active().aggregate(total=Sum("size_bytes"))["total"]
                    or 0
                ),
                "trash_files": FileItem.objects.trash().count(),
                "unsafe_files": FileItem.objects.filter(
                    status__in=[FileItem.STATUS_INFECTED, FileItem.STATUS_BLOCKED]
                ).count(),
                "expired_share_links": ShareLink.objects.expired().count(),
                "storage_by_user": storage_by_user,
                "file_types": file_types,
                "top_labels": top_labels,
                "recent_activity": ActivityLogSerializer(
                    ActivityLog.objects.select_related("user", "file", "folder")
                    .all()
                    .order_by("-created_at")[:10],
                    many=True,
                ).data,
            }
        )


class StaffStorageStatsAPIView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        active_files = FileItem.objects.active()
        return Response(
            {
                "total_users": User.objects.count(),
                "total_files": active_files.count(),
                "total_storage": active_files.aggregate(total=Sum("size_bytes"))["total"]
                or 0,
                "storage_by_user": list(FileItem.objects.storage_summary_by_user()),
            }
        )


class StaffFileSummaryAPIView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        top_labels = [
            {"id": label.id, "name": label.name, "file_count": label.file_count}
            for label in FileItem.objects.top_labels()
        ]
        return Response(
            {
                "file_types": list(FileItem.objects.file_type_summary()),
                "trash_files": FileItem.objects.trash().count(),
                "unsafe_files": FileItem.objects.filter(
                    status__in=[FileItem.STATUS_INFECTED, FileItem.STATUS_BLOCKED]
                ).count(),
                "expired_share_links": ShareLink.objects.expired().count(),
                "top_labels": top_labels,
            }
        )


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        keyword = self.request.GET.get("q", "").strip()
        owner = self.request.user

        root_folders = Folder.objects.roots().filter(owner=owner)
        upload_folders = Folder.objects.filter(
            owner=owner,
            is_deleted=False,
        ).order_by("name")
        active_files = FileItem.objects.active().filter(owner=owner)
        root_files = active_files.filter(folder__isnull=True)

        if keyword:
            root_files = active_files.search(keyword)
            root_folders = root_folders.filter(name__icontains=keyword)

        storage_used_bytes = (
            active_files.aggregate(total=Sum("size_bytes")).get("total") or 0
        )

        context.update(
            {
                "keyword": keyword,
                "root_folders": root_folders,
                "upload_folders": upload_folders,
                "root_files": root_files,
                "storage_used_bytes": storage_used_bytes,
                "storage_quota_bytes": (
                    owner.profile.quota_bytes if hasattr(owner, "profile") else 0
                ),
                "folder_form": FolderForm(owner=owner),
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        form = FolderForm(request.POST, owner=request.user)
        form.instance.owner = request.user
        if form.is_valid():
            form.save()
            return redirect("dashboard")

        context = self.get_context_data(**kwargs)
        context["folder_form"] = form
        return self.render_to_response(context)


class FolderDetailPageView(LoginRequiredMixin, TemplateView):
    template_name = "folder_detail.html"

    def get_folder(self):
        return get_object_or_404(
            Folder.objects.active(),
            pk=self.kwargs["pk"],
            owner=self.request.user,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        folder = self.get_folder()
        breadcrumb = []
        current = folder
        while current:
            breadcrumb.append(current)
            current = current.parent

        context.update(
            {
                "folder": folder,
                "breadcrumb": reversed(breadcrumb),
                "child_folders": folder.children.active().order_by("name"),
                "files": FileItem.objects.active()
                .in_folder(folder.pk)
                .owned_by(self.request.user)
                .prefetch_related("labels"),
                "folder_form": FolderForm(owner=self.request.user, initial={"parent": folder}),
                "folder_edit_form": FolderForm(
                    instance=folder,
                    owner=self.request.user,
                ),
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        folder = self.get_folder()
        if request.POST.get("action") == "edit":
            form = FolderForm(request.POST, instance=folder, owner=request.user)
            if form.is_valid():
                form.save()
                return redirect("folder-detail-page", pk=folder.pk)

            context = self.get_context_data(**kwargs)
            context["folder_edit_form"] = form
            return self.render_to_response(context)

        data = request.POST.copy()
        data["parent"] = folder.pk
        form = FolderForm(data, owner=request.user)
        form.instance.owner = request.user
        if form.is_valid():
            form.save()
            return redirect("folder-detail-page", pk=folder.pk)

        context = self.get_context_data(**kwargs)
        context["folder_form"] = form
        return self.render_to_response(context)


class FileDetailPageView(LoginRequiredMixin, TemplateView):
    template_name = "file_detail.html"

    def get_file(self):
        return get_object_or_404(
            FileItem.objects.active().prefetch_related("labels"),
            pk=self.kwargs["pk"],
            owner=self.request.user,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        file_item = self.get_file()
        context.update(
            {
                "file": file_item,
                "metadata_form": FileMetadataForm(
                    instance=file_item,
                    owner=self.request.user,
                ),
                "share_form": ShareLinkForm(
                    file_item=file_item,
                    created_by=self.request.user,
                ),
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        file_item = self.get_file()
        action = request.POST.get("action")

        if action == "share":
            form = ShareLinkForm(
                request.POST,
                file_item=file_item,
                created_by=request.user,
            )
            if form.is_valid():
                share_link = form.save(commit=False)
                share_link.file = file_item
                share_link.created_by = request.user
                share_link.save()
                ActivityLog.objects.create(
                    user=request.user,
                    action=ActivityLog.ACTION_SHARE,
                    file=file_item,
                    folder=file_item.folder,
                    detail=f"Created share link for {file_item.name}",
                )
                return redirect("shared-links-page")
            context = self.get_context_data(**kwargs)
            context["share_form"] = form
            return self.render_to_response(context)

        old_folder_id = file_item.folder_id
        form = FileMetadataForm(request.POST, instance=file_item, owner=request.user)
        if form.is_valid():
            updated_file = form.save()
            if updated_file.folder_id != old_folder_id:
                ActivityLog.objects.create(
                    user=request.user,
                    action=ActivityLog.ACTION_MOVE,
                    file=updated_file,
                    folder=updated_file.folder,
                    detail=f"Moved {updated_file.name}",
                )
            return redirect("file-detail-page", pk=file_item.pk)
        context = self.get_context_data(**kwargs)
        context["metadata_form"] = form
        return self.render_to_response(context)


class TrashPageView(LoginRequiredMixin, TemplateView):
    template_name = "trash.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["files"] = (
            FileItem.objects.trash()
            .owned_by(self.request.user)
            .select_related("folder")
        )
        context["folders"] = Folder.objects.trash().filter(owner=self.request.user)
        return context


class StarredPageView(LoginRequiredMixin, TemplateView):
    template_name = "starred.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["files"] = FileItem.objects.starred().owned_by(self.request.user)
        return context


class SharedLinksPageView(LoginRequiredMixin, TemplateView):
    template_name = "shared_links.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["share_links"] = ShareLink.objects.filter(
            created_by=self.request.user
        ).select_related("file")
        return context


class StaffDashboardPageView(UserPassesTestMixin, TemplateView):
    template_name = "staff_dashboard.html"

    def test_func(self):
        return self.request.user.is_staff

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        active_files = FileItem.objects.active()
        context.update(
            {
                "total_users": User.objects.count(),
                "total_files": active_files.count(),
                "total_storage": active_files.aggregate(total=Sum("size_bytes"))["total"] or 0,
                "trash_files": FileItem.objects.trash().count(),
                "unsafe_files": FileItem.objects.filter(
                    status__in=[FileItem.STATUS_INFECTED, FileItem.STATUS_BLOCKED]
                ).count(),
                "expired_links": ShareLink.objects.expired().count(),
                "top_users": FileItem.objects.storage_summary_by_user()[:5],
                "recent_activity": ActivityLog.objects.select_related("user", "file")
                .all()
                .order_by("-created_at")[:10],
            }
        )
        return context


class FileTrashPageActionView(LoginRequiredMixin, View):
    def post(self, request, pk, action):
        if action == "delete":
            file_item = get_object_or_404(
                FileItem.objects.active(), pk=pk, owner=request.user
            )
            file_item.is_deleted = True
            file_item.save()
            profile, _ = Profile.objects.get_or_create(user=request.user)
            profile.used_storage_bytes = max(
                0, profile.used_storage_bytes - file_item.size_bytes
            )
            profile.save(update_fields=["used_storage_bytes"])
            ActivityLog.objects.create(
                user=request.user,
                action=ActivityLog.ACTION_DELETE,
                file=file_item,
                folder=file_item.folder,
                detail=f"Moved {file_item.name} to trash",
            )
        elif action == "restore":
            file_item = get_object_or_404(
                FileItem.objects.trash(), pk=pk, owner=request.user
            )
            if file_item.folder and file_item.folder.is_deleted:
                return redirect("trash-page")
            profile, _ = Profile.objects.get_or_create(user=request.user)
            if profile.can_upload(file_item.size_bytes):
                file_item.is_deleted = False
                file_item.save()
                profile.used_storage_bytes += file_item.size_bytes
                profile.save(update_fields=["used_storage_bytes"])
                ActivityLog.objects.create(
                    user=request.user,
                    action=ActivityLog.ACTION_RESTORE,
                    file=file_item,
                    folder=file_item.folder,
                    detail=f"Restored {file_item.name}",
                )
        elif action == "permanent":
            file_item = get_object_or_404(
                FileItem.objects.trash(), pk=pk, owner=request.user
            )
            if file_item.file:
                file_item.file.delete(save=False)
            file_item.delete()
        return redirect("trash-page")


class FileStarPageActionView(LoginRequiredMixin, View):
    def post(self, request, pk, action):
        file_item = get_object_or_404(
            FileItem.objects.active(), pk=pk, owner=request.user
        )
        if action == "star":
            file_item.is_starred = True
        elif action == "unstar":
            file_item.is_starred = False
        else:
            return redirect("file-detail-page", pk=file_item.pk)

        file_item.save(update_fields=["is_starred", "updated_at"])
        if request.POST.get("next") == "starred":
            return redirect("starred-page")
        return redirect("file-detail-page", pk=file_item.pk)


class FolderTrashPageActionView(LoginRequiredMixin, View):
    def post(self, request, pk, action):
        folder = get_object_or_404(Folder, pk=pk, owner=request.user)
        folder_ids = folder_tree_ids(folder)

        if action == "delete" and not folder.is_deleted:
            deleted_at = timezone.now()
            files = FileItem.objects.filter(
                folder_id__in=folder_ids,
                is_deleted=False,
            )
            removed_size = files.aggregate(total=Sum("size_bytes"))["total"] or 0
            Folder.objects.filter(id__in=folder_ids).update(
                is_deleted=True, deleted_at=deleted_at
            )
            files.update(is_deleted=True, deleted_at=deleted_at)
            profile, _ = Profile.objects.get_or_create(user=request.user)
            profile.used_storage_bytes = max(
                0, profile.used_storage_bytes - removed_size
            )
            profile.save(update_fields=["used_storage_bytes"])
            ActivityLog.objects.create(
                user=request.user,
                action=ActivityLog.ACTION_DELETE,
                folder=folder,
                detail=f"Moved folder {folder.name} to trash",
            )
        elif (
            action == "restore"
            and folder.is_deleted
            and (folder.parent is None or not folder.parent.is_deleted)
        ):
            files = FileItem.objects.filter(folder_id__in=folder_ids, is_deleted=True)
            restore_size = files.aggregate(total=Sum("size_bytes"))["total"] or 0
            profile, _ = Profile.objects.get_or_create(user=request.user)
            if profile.can_upload(restore_size):
                Folder.objects.filter(id__in=folder_ids).update(
                    is_deleted=False, deleted_at=None
                )
                files.update(is_deleted=False, deleted_at=None)
                profile.used_storage_bytes += restore_size
                profile.save(update_fields=["used_storage_bytes"])
                ActivityLog.objects.create(
                    user=request.user,
                    action=ActivityLog.ACTION_RESTORE,
                    folder=folder,
                    detail=f"Restored folder {folder.name}",
                )
        elif action == "permanent" and folder.is_deleted:
            for file_item in FileItem.objects.filter(folder_id__in=folder_ids):
                if file_item.file:
                    file_item.file.delete(save=False)
            folder.delete()
        return redirect("trash-page")


class ShareLinkRevokePageView(LoginRequiredMixin, View):
    def post(self, request, pk):
        ShareLink.objects.filter(pk=pk, created_by=request.user).update(is_active=False)
        return redirect("shared-links-page")


class FolderListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = FolderSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Folder.objects.filter(
            owner=self.request.user,
            is_deleted=False,
        ).order_by("name")


class FolderDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = FolderSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrStaff]

    def get_queryset(self):
        queryset = Folder.objects.active()
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(owner=self.request.user)

    def perform_destroy(self, instance):
        folder_ids = folder_tree_ids(instance)
        deleted_at = timezone.now()
        files = FileItem.objects.filter(
            folder_id__in=folder_ids,
            is_deleted=False,
        )
        removed_size = files.aggregate(total=Sum("size_bytes"))["total"] or 0

        with transaction.atomic():
            Folder.objects.filter(id__in=folder_ids).update(
                is_deleted=True,
                deleted_at=deleted_at,
            )
            files.update(is_deleted=True, deleted_at=deleted_at)
            profile, _ = Profile.objects.get_or_create(user=instance.owner)
            profile.used_storage_bytes = max(0, profile.used_storage_bytes - removed_size)
            profile.save(update_fields=["used_storage_bytes"])
            ActivityLog.objects.create(
                user=self.request.user,
                action=ActivityLog.ACTION_DELETE,
                folder=instance,
                detail=f"Moved folder {instance.name} to trash",
            )


class FolderRestoreAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        folders = Folder.objects.filter(
            pk=pk,
            is_deleted=True,
        )
        if not request.user.is_staff:
            folders = folders.filter(owner=request.user)
        folder = get_object_or_404(folders)

        if folder.parent and folder.parent.is_deleted:
            return Response(
                {"parent": "Restore the parent folder first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        folder_ids = folder_tree_ids(folder)
        files = FileItem.objects.filter(folder_id__in=folder_ids, is_deleted=True)
        restore_size = files.aggregate(total=Sum("size_bytes"))["total"] or 0
        profile, _ = Profile.objects.get_or_create(user=folder.owner)
        if not profile.can_upload(restore_size):
            return Response(
                {"detail": "Not enough storage quota to restore this folder."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            Folder.objects.filter(id__in=folder_ids).update(
                is_deleted=False,
                deleted_at=None,
            )
            files.update(is_deleted=False, deleted_at=None)
            profile.used_storage_bytes += restore_size
            profile.save(update_fields=["used_storage_bytes"])
            ActivityLog.objects.create(
                user=request.user,
                action=ActivityLog.ACTION_RESTORE,
                folder=folder,
                detail=f"Restored folder {folder.name}",
            )

        folder.refresh_from_db()

        return Response(FolderSerializer(folder).data, status=status.HTTP_200_OK)


class FileListAPIView(generics.ListAPIView):
    serializer_class = FileListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = (
            FileItem.objects.active()
            .filter(owner=self.request.user)
            .select_related("owner", "folder")
            .prefetch_related("labels")
            .order_by("-created_at")
        )

        keyword = self.request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.search(keyword)

        folder_id = self.request.query_params.get("folder")
        if folder_id:
            queryset = queryset.in_folder(folder_id)

        if self.request.query_params.get("starred") in {"1", "true"}:
            queryset = queryset.starred()

        file_type = self.request.query_params.get("type", "").strip()
        if file_type:
            queryset = queryset.by_type(file_type)

        min_bytes = self.request.query_params.get("min_bytes")
        max_bytes = self.request.query_params.get("max_bytes")
        if min_bytes or max_bytes:
            try:
                min_value = int(min_bytes) if min_bytes else None
                max_value = int(max_bytes) if max_bytes else None
            except ValueError:
                raise ValidationError(
                    {"min_bytes": "min_bytes and max_bytes must be integers."}
                )
            queryset = queryset.size_between(
                min_value,
                max_value,
            )

        return queryset


class FileUploadAPIView(generics.CreateAPIView):
    serializer_class = FileUploadSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def perform_create(self, serializer):
        with transaction.atomic():
            file_item = serializer.save()

            profile = self.request.user.profile
            profile.used_storage_bytes += file_item.size_bytes
            profile.save(update_fields=["used_storage_bytes"])

            ActivityLog.objects.create(
                user=self.request.user,
                action=ActivityLog.ACTION_UPLOAD,
                file=file_item,
                folder=file_item.folder,
                detail=f"Uploaded {file_item.name}",
            )

            transaction.on_commit(
                lambda: scan_uploaded_file.delay(file_item.id)
            )


class FileDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated, IsOwnerOrStaff]

    def get_queryset(self):
        queryset = (
            FileItem.objects.active()
            .select_related("owner", "folder")
            .prefetch_related("labels")
        )
        if self.request.user.is_staff:
            return queryset
        return queryset.filter(owner=self.request.user)

    def get_serializer_class(self):
        if self.request.method in {"PUT", "PATCH"}:
            return FileUpdateSerializer
        return FileListSerializer

    def perform_update(self, serializer):
        old_folder_id = serializer.instance.folder_id
        file_item = serializer.save()
        if file_item.folder_id != old_folder_id:
            ActivityLog.objects.create(
                user=self.request.user,
                action=ActivityLog.ACTION_MOVE,
                file=file_item,
                folder=file_item.folder,
                detail=f"Moved {file_item.name}",
            )

    def perform_destroy(self, instance):
        with transaction.atomic():
            instance.is_deleted = True
            instance.save()

            profile = instance.owner.profile
            profile.used_storage_bytes = max(
                0,
                profile.used_storage_bytes - instance.size_bytes,
            )
            profile.save(update_fields=["used_storage_bytes"])

            ActivityLog.objects.create(
                user=self.request.user,
                action=ActivityLog.ACTION_DELETE,
                file=instance,
                folder=instance.folder,
                detail=f"Moved {instance.name} to trash",
            )


class TrashListAPIView(generics.ListAPIView):
    serializer_class = FileListSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            FileItem.objects.trash()
            .filter(owner=self.request.user)
            .select_related("owner", "folder")
            .prefetch_related("labels")
            .order_by("-deleted_at")
        )


class TrashFolderListAPIView(generics.ListAPIView):
    serializer_class = FolderSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Folder.objects.trash().filter(owner=self.request.user).order_by(
            "-deleted_at"
        )


class FileRestoreAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        files = FileItem.objects.filter(
            pk=pk,
            is_deleted=True,
        )
        if not request.user.is_staff:
            files = files.filter(owner=request.user)
        file_item = get_object_or_404(files)

        if file_item.folder and file_item.folder.is_deleted:
            return Response(
                {"folder": "Restore the folder first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not hasattr(file_item.owner, "profile"):
            return Response(
                {"detail": "User profile does not exist."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        profile = file_item.owner.profile
        if not profile.can_upload(file_item.size_bytes):
            return Response(
                {"detail": "Not enough storage quota to restore this file."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            file_item.is_deleted = False
            file_item.save()

            profile.used_storage_bytes += file_item.size_bytes
            profile.save(update_fields=["used_storage_bytes"])

            ActivityLog.objects.create(
                user=request.user,
                action=ActivityLog.ACTION_RESTORE,
                file=file_item,
                folder=file_item.folder,
                detail=f"Restored {file_item.name}",
            )

        return Response(FileListSerializer(file_item).data, status=status.HTTP_200_OK)


class FileStarAPIView(APIView):
    permission_classes = [IsAuthenticated]
    is_starred = True

    def post(self, request, pk):
        file_item = get_object_or_404(
            FileItem.objects.active(),
            pk=pk,
            owner=request.user,
        )
        file_item.is_starred = self.is_starred
        file_item.save(update_fields=["is_starred", "updated_at"])
        return Response({"id": file_item.pk, "is_starred": file_item.is_starred})


class FileUnstarAPIView(FileStarAPIView):
    is_starred = False


class FilePermanentDeleteAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        file_item = get_object_or_404(
            FileItem.objects.trash(),
            pk=pk,
            owner=request.user,
        )
        if file_item.file:
            file_item.file.delete(save=False)
        file_item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FolderPermanentDeleteAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        folder = get_object_or_404(
            Folder.objects.trash(),
            pk=pk,
            owner=request.user,
        )
        folder_ids = folder_tree_ids(folder)
        for file_item in FileItem.objects.filter(folder_id__in=folder_ids):
            if file_item.file:
                file_item.file.delete(save=False)
        folder.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ShareLinkListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = ShareLinkSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ShareLink.objects.filter(
            created_by=self.request.user,
        ).select_related("file").order_by("-created_at")

    def perform_create(self, serializer):
        with transaction.atomic():
            share_link = serializer.save()

            ActivityLog.objects.create(
                user=self.request.user,
                action=ActivityLog.ACTION_SHARE,
                file=share_link.file,
                folder=share_link.file.folder,
                detail=f"Created share link for {share_link.file.name}",
            )


class FileShareLinkCreateAPIView(generics.CreateAPIView):
    serializer_class = ShareLinkSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        file_item = get_object_or_404(
            FileItem.objects.active(),
            pk=kwargs["pk"],
            owner=request.user,
        )
        data = request.data.copy()
        data["file"] = file_item.pk
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        share_link = serializer.save()
        ActivityLog.objects.create(
            user=request.user,
            action=ActivityLog.ACTION_SHARE,
            file=file_item,
            folder=file_item.folder,
            detail=f"Created share link for {file_item.name}",
        )
        return Response(
            self.get_serializer(share_link).data,
            status=status.HTTP_201_CREATED,
        )


class ShareLinkDestroyAPIView(generics.DestroyAPIView):
    serializer_class = ShareLinkSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ShareLink.objects.filter(created_by=self.request.user)

    def perform_destroy(self, instance):
        ShareLink.objects.filter(pk=instance.pk).update(is_active=False)


class SharedFileViewAPIView(generics.RetrieveAPIView):
    serializer_class = FileListSerializer
    permission_classes = [CanViewFile]

    def get_queryset(self):
        return (
            FileItem.objects.active()
            .select_related("owner", "folder")
            .prefetch_related("labels")
        )

    def retrieve(self, request, *args, **kwargs):
        file_item = self.get_object()
        token = request.query_params.get("token")

        if token:
            ShareLink.objects.active().filter(
                file=file_item,
                token=token,
            ).update(view_count=F("view_count") + 1)

        return Response(self.get_serializer(file_item).data)


class FileDownloadAPIView(APIView):
    permission_classes = [CanDownloadFile]

    def dispatch(self, request, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        request = self.initialize_request(request, *args, **kwargs)
        self.request = request
        self.headers = self.default_response_headers

        try:
            self.initial(request, *args, **kwargs)
            self.file_item = get_object_or_404(
                FileItem.objects.active().select_related("owner", "folder"),
                pk=kwargs["pk"],
            )
            self.check_object_permissions(request, self.file_item)
            if self.file_item.status != FileItem.STATUS_READY:
                raise PermissionDenied("File is not ready for download.")

            if request.method.lower() in self.http_method_names:
                handler = getattr(
                    self,
                    request.method.lower(),
                    self.http_method_not_allowed,
                )
            else:
                handler = self.http_method_not_allowed
            response = handler(request, *args, **kwargs)
        except Exception as error:
            response = self.handle_exception(error)

        self.response = self.finalize_response(request, response, *args, **kwargs)
        return self.response

    def get(self, request, pk):
        file_item = self.file_item

        FileItem.objects.filter(pk=file_item.pk).update(
            download_count=F("download_count") + 1,
        )

        token = request.query_params.get("token")
        if token:
            ShareLink.objects.active().filter(
                file=file_item,
                token=token,
            ).update(view_count=F("view_count") + 1)

        if file_item.file:
            return FileResponse(
                file_item.file.open("rb"),
                as_attachment=True,
                filename=file_item.name,
            )

        if file_item.external_url:
            return redirect(file_item.external_url)

        return Response(
            {"detail": "File content does not exist."},
            status=status.HTTP_404_NOT_FOUND,
        )
