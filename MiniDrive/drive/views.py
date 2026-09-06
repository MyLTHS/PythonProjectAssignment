from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView
from rest_framework import generics, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ActivityLog, FileItem, Folder
from .serializers import (
    FileListSerializer,
    FileUpdateSerializer,
    FileUploadSerializer,
    FolderSerializer,
)


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        keyword = self.request.GET.get("q", "").strip()
        owner = self.request.user

        root_folders = Folder.objects.roots().filter(owner=owner)
        root_files = FileItem.objects.active().filter(owner=owner, folder__isnull=True)
        active_files = FileItem.objects.active().filter(owner=owner)

        if keyword:
            root_files = root_files.search(keyword)
            root_folders = root_folders.filter(name__icontains=keyword)

        storage_used_bytes = (
            active_files.aggregate(total=Sum("size_bytes")).get("total") or 0
        )

        context.update(
            {
                "keyword": keyword,
                "root_folders": root_folders,
                "root_files": root_files,
                "storage_used_bytes": storage_used_bytes,
                "storage_quota_bytes": (
                    owner.profile.quota_bytes if hasattr(owner, "profile") else 0
                ),
            }
        )
        return context


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
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Folder.objects.filter(
            owner=self.request.user,
            is_deleted=False,
        )

    def perform_destroy(self, instance):
        instance.is_deleted = True
        instance.save()


class FolderRestoreAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        folder = get_object_or_404(
            Folder,
            pk=pk,
            owner=request.user,
            is_deleted=True,
        )

        if folder.parent and folder.parent.is_deleted:
            return Response(
                {"parent": "Restore the parent folder first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        folder.is_deleted = False

        try:
            folder.save()
        except DjangoValidationError as error:
            return Response(error.message_dict, status=status.HTTP_400_BAD_REQUEST)

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


class FileDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            FileItem.objects.active()
            .filter(owner=self.request.user)
            .select_related("owner", "folder")
            .prefetch_related("labels")
        )

    def get_serializer_class(self):
        if self.request.method in {"PUT", "PATCH"}:
            return FileUpdateSerializer
        return FileListSerializer

    def perform_destroy(self, instance):
        with transaction.atomic():
            instance.is_deleted = True
            instance.save()

            profile = self.request.user.profile
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


class FileRestoreAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        file_item = get_object_or_404(
            FileItem,
            pk=pk,
            owner=request.user,
            is_deleted=True,
        )

        if file_item.folder and file_item.folder.is_deleted:
            return Response(
                {"folder": "Restore the folder first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not hasattr(request.user, "profile"):
            return Response(
                {"detail": "User profile does not exist."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        profile = request.user.profile
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
