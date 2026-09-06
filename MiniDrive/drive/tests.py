from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

from .models import FileItem, Folder, Profile, ShareLink


class CustomManagerAvailabilityTests(TestCase):
    def test_file_item_manager_exposes_queryset_methods(self):
        self.assertTrue(hasattr(FileItem.objects, "active"))
        self.assertTrue(hasattr(FileItem.objects, "trash"))
        self.assertTrue(hasattr(FileItem.objects, "search"))

    def test_folder_manager_exposes_roots(self):
        self.assertTrue(hasattr(Folder.objects, "roots"))

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
