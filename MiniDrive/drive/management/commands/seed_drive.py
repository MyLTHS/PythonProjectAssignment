from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from drive.models import FileItem, Folder, Label, Profile


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

        missing_labels = [
            Label(name=name, slug=slugify(name), color=color)
            for name, color in [("Work", "#1a73e8"), ("Important", "#d93025")]
            if not Label.objects.filter(slug=slugify(name)).exists()
        ]
        Label.objects.bulk_create(missing_labels)

        owner = users["demo_user1"]
        documents, _ = Folder.objects.get_or_create(owner=owner, name="Documents")
        reports, _ = Folder.objects.get_or_create(
            owner=owner,
            parent=documents,
            name="Reports",
        )
        django_file, _ = FileItem.objects.get_or_create(
            owner=owner,
            folder=documents,
            name="Django documentation",
            defaults={
                "external_url": "https://docs.djangoproject.com/",
                "status": FileItem.STATUS_READY,
                "description": "Sample external file for local testing.",
            },
        )
        report_file, _ = FileItem.objects.get_or_create(
            owner=owner,
            folder=reports,
            name="Monthly report",
            defaults={
                "external_url": "https://example.com/monthly-report",
                "status": FileItem.STATUS_READY,
                "description": "Sample file inside a child folder.",
            },
        )

        second_owner = users["demo_user2"]
        personal, _ = Folder.objects.get_or_create(
            owner=second_owner,
            name="Personal",
        )
        personal_file, _ = FileItem.objects.get_or_create(
            owner=second_owner,
            folder=personal,
            name="Python website",
            defaults={
                "external_url": "https://www.python.org/",
                "status": FileItem.STATUS_READY,
                "description": "Sample file for demo_user2.",
            },
        )

        work_label = Label.objects.get(slug="work")
        important_label = Label.objects.get(slug="important")
        django_file.labels.add(work_label)
        report_file.labels.add(work_label, important_label)
        personal_file.labels.add(important_label)

        self.stdout.write(self.style.SUCCESS("Demo data is ready."))
        for username, password, _, _ in self.accounts:
            self.stdout.write(f"{username}: {password}")
