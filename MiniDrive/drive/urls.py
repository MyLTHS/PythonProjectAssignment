from django.urls import path

from .views import (
    DashboardView,
    FileDetailAPIView,
    FileDownloadAPIView,
    FileListAPIView,
    FileRestoreAPIView,
    FileUploadAPIView,
    FolderDetailAPIView,
    FolderListCreateAPIView,
    FolderRestoreAPIView,
    LoginAPIView,
    LogoutAPIView,
    SharedFileViewAPIView,
    ShareLinkDestroyAPIView,
    ShareLinkListCreateAPIView,
    TrashListAPIView,
)


urlpatterns = [
    path("", DashboardView.as_view(), name="dashboard"),
    path("api/auth/login/", LoginAPIView.as_view(), name="api-login"),
    path("api/auth/logout/", LogoutAPIView.as_view(), name="api-logout"),
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
    path(
        "api/share-links/",
        ShareLinkListCreateAPIView.as_view(),
        name="share-link-list-create",
    ),
    path(
        "api/share-links/<int:pk>/",
        ShareLinkDestroyAPIView.as_view(),
        name="share-link-destroy",
    ),
    path(
        "api/files/<int:pk>/view/",
        SharedFileViewAPIView.as_view(),
        name="shared-file-view",
    ),
    path(
        "api/files/<int:pk>/download/",
        FileDownloadAPIView.as_view(),
        name="file-download",
    ),
]
