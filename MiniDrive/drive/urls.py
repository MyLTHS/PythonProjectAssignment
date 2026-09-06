from django.urls import path

from .views import (
    DashboardView,
    FileDetailAPIView,
    FileListAPIView,
    FileRestoreAPIView,
    FileUploadAPIView,
    FolderDetailAPIView,
    FolderListCreateAPIView,
    FolderRestoreAPIView,
    TrashListAPIView,
)


urlpatterns = [
    path("", DashboardView.as_view(), name="dashboard"),
    path(
        "api/folders/",
        FolderListCreateAPIView.as_view(),
        name="folder-list-create",
    ),
    path(
        "api/folders/<int:pk>/",
        FolderDetailAPIView.as_view(),
        name="folder-detail",
    ),
    path(
        "api/folders/<int:pk>/restore/",
        FolderRestoreAPIView.as_view(),
        name="folder-restore",
    ),
    path("api/files/", FileListAPIView.as_view(), name="file-list"),
    path("api/files/upload/", FileUploadAPIView.as_view(), name="file-upload"),
    path(
        "api/files/<int:pk>/",
        FileDetailAPIView.as_view(),
        name="file-detail",
    ),
    path(
        "api/files/<int:pk>/restore/",
        FileRestoreAPIView.as_view(),
        name="file-restore",
    ),
    path("api/trash/", TrashListAPIView.as_view(), name="trash-list"),
]
