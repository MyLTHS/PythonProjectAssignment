from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify

from drive.models import (
    ActivityLog,
    FileItem,
    FileShare,
    Folder,
    Label,
    Profile,
    ShareLink,
)


class Command(BaseCommand):
    help = "Create local demo accounts and sample MiniDrive data"

    accounts = [
        ("demo_admin", "DemoAdmin123!", True, True),
        ("demo_staff", "DemoStaff123!", True, False),
        ("demo_user1", "DemoUser123!", False, False),
        ("demo_user2", "DemoUser123!", False, False),
    ]

    def handle(self, *args, **options):
        users = {}
        for username, password, is_staff, is_superuser in self.accounts:
            user, _ = User.objects.get_or_create(username=username)
            user.is_staff = is_staff
            user.is_superuser = is_superuser
            user.set_password(password)
            user.save()
            Profile.objects.get_or_create(user=user)
            users[username] = user

        for name, color in [("Work", "#1a73e8"), ("Important", "#d93025")]:
            Label.objects.update_or_create(
                slug=slugify(name),
                defaults={"name": name, "color": color},
            )

        owner = users["demo_user1"]
        documents, _ = Folder.objects.get_or_create(owner=owner, name="Documents")
        reports, _ = Folder.objects.get_or_create(
            owner=owner,
            parent=documents,
            name="Reports",
        )
        django_file, _ = FileItem.objects.update_or_create(
            owner=owner,
            folder=documents,
            name="Django documentation",
            defaults={
                "external_url": "https://docs.djangoproject.com/",
                "status": FileItem.STATUS_READY,
                "description": "Sample external file for local testing.",
                "mime_type": "text/html",
                "is_starred": True,
                "is_deleted": False,
                "deleted_at": None,
            },
        )
        report_file, _ = FileItem.objects.update_or_create(
            owner=owner,
            folder=reports,
            name="Monthly report",
            defaults={
                "external_url": "https://example.com/monthly-report",
                "status": FileItem.STATUS_READY,
                "description": "Sample file inside a child folder.",
                "mime_type": "application/pdf",
                "is_deleted": False,
                "deleted_at": None,
            },
        )

        second_owner = users["demo_user2"]
        personal, _ = Folder.objects.get_or_create(
            owner=second_owner,
            name="Personal",
        )
        personal_file, _ = FileItem.objects.update_or_create(
            owner=second_owner,
            folder=personal,
            name="Python website",
            defaults={
                "external_url": "https://www.python.org/",
                "status": FileItem.STATUS_READY,
                "description": "Sample file for demo_user2.",
                "mime_type": "text/html",
                "is_deleted": False,
                "deleted_at": None,
            },
        )

        archived_file, _ = FileItem.objects.update_or_create(
            owner=owner,
            folder=None,
            name="Archived note",
            defaults={
                "external_url": "https://example.com/archived-note",
                "status": FileItem.STATUS_READY,
                "description": "Sample file used to test trash and restore.",
                "mime_type": "text/plain",
                "is_deleted": True,
                "deleted_at": timezone.now(),
            },
        )

        work_label = Label.objects.get(slug="work")
        important_label = Label.objects.get(slug="important")
        django_file.labels.add(work_label)
        report_file.labels.add(work_label, important_label)
        personal_file.labels.add(important_label)

        ShareLink.objects.update_or_create(
            token="demo-view-token",
            defaults={
                "file": django_file,
                "created_by": owner,
                "permission": ShareLink.PERMISSION_VIEW,
                "recipient_email": "viewer@example.com",
                "is_active": True,
                "expires_at": None,
            },
        )
        ShareLink.objects.update_or_create(
            token="demo-download-token",
            defaults={
                "file": report_file,
                "created_by": owner,
                "permission": ShareLink.PERMISSION_DOWNLOAD,
                "recipient_email": "download@example.com",
                "is_active": True,
                "expires_at": None,
            },
        )

        FileShare.objects.update_or_create(
            file=report_file,
            shared_by=owner,
            shared_with=second_owner,
            defaults={
                "permission": FileShare.PERMISSION_VIEWER,
                "accepted": True,
            },
        )

        ActivityLog.objects.get_or_create(
            user=owner,
            action=ActivityLog.ACTION_UPLOAD,
            file=django_file,
            folder=documents,
            detail="Uploaded Django documentation",
        )
        ActivityLog.objects.get_or_create(
            user=owner,
            action=ActivityLog.ACTION_SHARE,
            file=report_file,
            folder=reports,
            detail="Shared Monthly report with demo_user2",
        )
        ActivityLog.objects.get_or_create(
            user=owner,
            action=ActivityLog.ACTION_DELETE,
            file=archived_file,
            detail="Moved Archived note to trash",
        )

        self.stdout.write(self.style.SUCCESS("Demo data is ready."))
        for username, password, _, _ in self.accounts:
            self.stdout.write(f"{username}: {password}")
