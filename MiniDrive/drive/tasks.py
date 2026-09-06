from pathlib import Path

from celery import shared_task
from django.db.models import Sum

from .models import ActivityLog, FileItem, Folder, Profile, ShareLink


@shared_task
def scan_uploaded_file(file_id):
    file_item = FileItem.objects.filter(pk=file_id, is_deleted=False).first()
    if not file_item or not file_item.file:
        return "File not found"

    file_item.file.open("rb")
    try:
        content = file_item.file.read(1024 * 1024)
    finally:
        file_item.file.close()

    extension = Path(file_item.name).suffix.lower()
    allowed_extensions = {".txt", ".pdf", ".png", ".jpg", ".jpeg", ".csv", ".xlsx", ".zip"}
    blocked_extensions = {".exe", ".bat", ".sh"}
    allowed_mime_types = {
        "text/plain",
        "text/csv",
        "application/pdf",
        "image/png",
        "image/jpeg",
        "application/zip",
        "application/x-zip-compressed",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    max_size = 20 * 1024 * 1024
    eicar_signature = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"

    if eicar_signature in content:
        file_item.status = FileItem.STATUS_INFECTED
    elif (
        extension in blocked_extensions
        or extension not in allowed_extensions
        or file_item.mime_type not in allowed_mime_types
        or file_item.size_bytes > max_size
    ):
        file_item.status = FileItem.STATUS_BLOCKED
    else:
        file_item.status = FileItem.STATUS_READY

    file_item.save(update_fields=["status", "updated_at"])
    ActivityLog.objects.create(
        user=file_item.owner,
        action=ActivityLog.ACTION_SCAN,
        file=file_item,
        folder=file_item.folder,
        detail=f"Scan result: {file_item.status}",
    )
    return file_item.status


@shared_task
def purge_trash(days=30):
    file_ids = list(FileItem.objects.due_for_purge(days).values_list("id", flat=True))
    files = list(FileItem.objects.filter(id__in=file_ids).select_related("owner", "folder"))
    logs = [
        ActivityLog(
            user=file_item.owner,
            action=ActivityLog.ACTION_PURGE,
            file=file_item,
            folder=file_item.folder,
            detail=f"Permanently deleted {file_item.name}",
        )
        for file_item in files
    ]
    ActivityLog.objects.bulk_create(logs)

    for file_item in files:
        if file_item.file:
            file_item.file.delete(save=False)
        file_item.delete()

    folder_ids = list(Folder.objects.due_for_purge(days).values_list("id", flat=True))
    folders = list(Folder.objects.filter(id__in=folder_ids).select_related("owner"))
    ActivityLog.objects.bulk_create(
        [
            ActivityLog(
                user=folder.owner,
                action=ActivityLog.ACTION_PURGE,
                folder=folder,
                detail=f"Permanently deleted folder {folder.name}",
            )
            for folder in folders
        ]
    )

    folder_tree_ids = set(folder_ids)
    pending_ids = folder_ids
    while pending_ids:
        child_ids = list(
            Folder.objects.filter(parent_id__in=pending_ids).values_list(
                "id", flat=True
            )
        )
        folder_tree_ids.update(child_ids)
        pending_ids = child_ids

    folder_files = FileItem.objects.filter(folder_id__in=folder_tree_ids)
    for file_item in folder_files:
        if file_item.file:
            file_item.file.delete(save=False)
    Folder.objects.filter(id__in=folder_tree_ids).delete()

    return len(files) + len(folders)


@shared_task
def expire_share_links():
    links = list(
        ShareLink.objects.expired()
        .filter(is_active=True)
        .select_related("created_by", "file", "file__folder")
    )

    for share_link in links:
        ShareLink.objects.filter(pk=share_link.pk).update(is_active=False)
        ActivityLog.objects.create(
            user=share_link.created_by,
            action=ActivityLog.ACTION_EXPIRE,
            file=share_link.file,
            folder=share_link.file.folder,
            detail=f"Expired share link for {share_link.file.name}",
        )

    return len(links)


@shared_task
def recalculate_user_storage():
    storage_by_user = {
        row["owner_id"]: row["total"] or 0
        for row in (
            FileItem.objects.active()
            .values("owner_id")
            .annotate(total=Sum("size_bytes"))
        )
    }

    profiles = list(Profile.objects.all())
    for profile in profiles:
        profile.used_storage_bytes = storage_by_user.get(profile.user_id, 0)

    Profile.objects.bulk_update(profiles, ["used_storage_bytes"])
    return len(profiles)
