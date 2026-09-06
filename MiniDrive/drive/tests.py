from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from datetime import timedelta
from io import StringIO
from tempfile import TemporaryDirectory

from .models import FileItem, Folder, Label, Profile, ShareLink
from .tasks import purge_trash, scan_uploaded_file


class CustomManagerAvailabilityTests(TestCase):
    def test_file_item_manager_exposes_queryset_methods(self):
        methods = [
            "active",
            "trash",
            "starred",
            "ready",
            "in_folder",
            "owned_by",
            "search",
            "by_type",
            "size_between",
            "updated_between",
            "due_for_purge",
        ]
        for method in methods:
            self.assertTrue(hasattr(FileItem.objects, method), method)

    def test_folder_manager_exposes_queryset_methods(self):
        for method in ["active", "trash", "roots", "due_for_purge"]:
            self.assertTrue(hasattr(Folder.objects, method), method)

    def test_share_link_manager_exposes_queryset_methods(self):
        self.assertTrue(hasattr(ShareLink.objects, "active"))
        self.assertTrue(hasattr(ShareLink.objects, "expired"))


class DashboardViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="lym", password="secret123")
        self.other_user = User.objects.create_user(
            username="other", password="secret123"
        )
        Profile.objects.get_or_create(user=self.user)
        Profile.objects.get_or_create(user=self.other_user)

    def test_dashboard_requires_login(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)

    def test_dashboard_shows_only_current_user_root_items(self):
        self.client.login(username="lym", password="secret123")

        root_folder = Folder.objects.create(owner=self.user, name="Root Work")
        Folder.objects.create(owner=self.user, name="Deleted Root", is_deleted=True)
        child_folder = Folder.objects.create(
            owner=self.user,
            parent=root_folder,
            name="Child Folder",
        )
        Folder.objects.create(owner=self.other_user, name="Other Root")

        root_file = FileItem.objects.create(
            owner=self.user,
            name="report.pdf",
            file=SimpleUploadedFile("report.pdf", b"demo pdf"),
            status=FileItem.STATUS_READY,
        )
        nested_file = FileItem.objects.create(
            owner=self.user,
            folder=child_folder,
            name="nested.txt",
            file=SimpleUploadedFile("nested.txt", b"nested file"),
            status=FileItem.STATUS_READY,
        )
        FileItem.objects.create(
            owner=self.user,
            name="trash.txt",
            file=SimpleUploadedFile("trash.txt", b"trash"),
            is_deleted=True,
            deleted_at="2026-08-01T10:00:00Z",
            status=FileItem.STATUS_READY,
        )
        FileItem.objects.create(
            owner=self.other_user,
            name="other.txt",
            file=SimpleUploadedFile("other.txt", b"other"),
            status=FileItem.STATUS_READY,
        )

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Root Work")
        self.assertContains(response, "report.pdf")
        self.assertNotContains(response, "Deleted Root")
        self.assertNotIn(child_folder, response.context["root_folders"])
        self.assertNotContains(response, "nested.txt")
        self.assertNotContains(response, "trash.txt")
        self.assertNotContains(response, "other.txt")
        self.assertEqual(
            response.context["storage_used_bytes"],
            root_file.size_bytes + nested_file.size_bytes,
        )


class UserFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user", password="secret123")
        Profile.objects.get_or_create(user=self.user)
        self.client.login(username="user", password="secret123")
        self.folder = Folder.objects.create(owner=self.user, name="Documents")
        self.file_item = FileItem.objects.create(
            owner=self.user,
            name="notes.txt",
            file=SimpleUploadedFile("notes.txt", b"hello"),
            status=FileItem.STATUS_READY,
        )

    def test_required_template_pages_are_available(self):
        routes = [
            reverse("folder-detail-page", args=[self.folder.pk]),
            reverse("file-detail-page", args=[self.file_item.pk]),
            reverse("trash-page"),
            reverse("starred-page"),
            reverse("shared-links-page"),
        ]
        for route in routes:
            self.assertEqual(self.client.get(route).status_code, 200, route)

    def test_star_and_unstar_file(self):
        star_response = self.client.post(
            reverse("file-star", args=[self.file_item.pk])
        )
        self.assertEqual(star_response.status_code, 200)
        self.file_item.refresh_from_db()
        self.assertTrue(self.file_item.is_starred)

        unstar_response = self.client.post(
            reverse("file-unstar", args=[self.file_item.pk])
        )
        self.assertEqual(unstar_response.status_code, 200)
        self.file_item.refresh_from_db()
        self.assertFalse(self.file_item.is_starred)

    def test_permanent_delete_removes_trashed_file(self):
        self.file_item.is_deleted = True
        self.file_item.save()

        response = self.client.delete(
            reverse("file-permanent-delete", args=[self.file_item.pk])
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(FileItem.objects.filter(pk=self.file_item.pk).exists())

    def test_active_files_exclude_deleted_folders(self):
        nested_file = FileItem.objects.create(
            owner=self.user,
            folder=self.folder,
            name="nested.txt",
            file=SimpleUploadedFile("nested.txt", b"nested"),
            status=FileItem.STATUS_READY,
        )
        self.folder.is_deleted = True
        self.folder.save()

        self.assertNotIn(nested_file, FileItem.objects.active())


class ScanUploadedFileTests(TestCase):
    def test_scan_blocks_a_file_with_an_invalid_mime_type(self):
        user = User.objects.create_user(username="scanner", password="secret123")
        file_item = FileItem.objects.create(
            owner=user,
            name="document.txt",
            file=SimpleUploadedFile("document.txt", b"safe content"),
        )
        FileItem.objects.filter(pk=file_item.pk).update(
            mime_type="application/x-msdownload"
        )

        scan_uploaded_file(file_item.pk)

        file_item.refresh_from_db()
        self.assertEqual(file_item.status, FileItem.STATUS_BLOCKED)

    def test_purge_folder_removes_files_inside_child_folders(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            user = User.objects.create_user(username="purger", password="secret123")
            parent = Folder.objects.create(owner=user, name="Parent")
            child = Folder.objects.create(owner=user, parent=parent, name="Child")
            file_item = FileItem.objects.create(
                owner=user,
                folder=child,
                name="old.txt",
                file=SimpleUploadedFile("old.txt", b"old file"),
            )
            stored_name = file_item.file.name
            Folder.objects.filter(pk=parent.pk).update(
                is_deleted=True,
                deleted_at=timezone.now() - timedelta(days=31),
            )

            self.assertTrue(file_item.file.storage.exists(stored_name))
            purge_trash()

            self.assertFalse(FileItem.objects.filter(pk=file_item.pk).exists())
            self.assertFalse(file_item.file.storage.exists(stored_name))


class SeedDriveCommandTests(TestCase):
    def test_seed_command_can_run_twice(self):
        output = StringIO()
        call_command("seed_drive", stdout=output)
        call_command("seed_drive", stdout=output)

        self.assertEqual(User.objects.filter(username__startswith="demo_").count(), 4)
        self.assertTrue(Label.objects.filter(name="Work", slug="work").exists())
        self.assertTrue(Label.objects.filter(name="Important", slug="important").exists())

    def test_seed_command_reuses_an_existing_slug(self):
        Label.objects.create(name="work", slug="work")

        call_command("seed_drive", stdout=StringIO())

        self.assertEqual(Label.objects.filter(slug="work").count(), 1)
