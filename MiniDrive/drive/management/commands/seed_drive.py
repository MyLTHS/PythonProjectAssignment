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
        folder, _ = Folder.objects.get_or_create(owner=owner, name="Documents")
        FileItem.objects.get_or_create(
            owner=owner,
            folder=folder,
            name="Django documentation",
            defaults={
                "external_url": "https://docs.djangoproject.com/",
                "status": FileItem.STATUS_READY,
                "description": "Sample external file for local testing.",
            },
        )

        self.stdout.write(self.style.SUCCESS("Demo data is ready."))
        for username, password, _, _ in self.accounts:
            self.stdout.write(f"{username}: {password}")
