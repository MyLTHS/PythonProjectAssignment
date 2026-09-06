from datetime import timedelta
from io import StringIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import ActivityLog, FileItem, Folder, Label, Profile, ShareLink
from .tasks import purge_trash, scan_uploaded_file
from .admin import FolderAdmin


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

    def test_expired_links_only_returns_active_links(self):
        user = User.objects.create_user(username="link-owner", password="secret123")
        file_item = FileItem.objects.create(
            owner=user,
            name="link.txt",
            file=SimpleUploadedFile("link.txt", b"link"),
            status=FileItem.STATUS_READY,
        )
        expired_at = timezone.now() - timedelta(hours=1)
        active_link = ShareLink.objects.create(
            file=file_item,
            created_by=user,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        inactive_link = ShareLink.objects.create(
            file=file_item,
            created_by=user,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        ShareLink.objects.filter(pk__in=[active_link.pk, inactive_link.pk]).update(
            expires_at=expired_at
        )
        ShareLink.objects.filter(pk=inactive_link.pk).update(is_active=False)

        self.assertIn(active_link, ShareLink.objects.expired())
        self.assertNotIn(inactive_link, ShareLink.objects.expired())


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

    def test_dashboard_contains_ajax_upload_code(self):
        self.client.login(username="lym", password="secret123")

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "new FormData(uploadForm)")
        self.assertContains(response, '"X-CSRFToken": csrfToken')
        self.assertContains(response, 'event.preventDefault()')

    def test_search_finds_a_file_inside_a_child_folder(self):
        self.client.login(username="lym", password="secret123")
        folder = Folder.objects.create(owner=self.user, name="Reports")
        FileItem.objects.create(
            owner=self.user,
            folder=folder,
            name="monthly-report.txt",
            file=SimpleUploadedFile("monthly-report.txt", b"report"),
            status=FileItem.STATUS_READY,
        )

        response = self.client.get(reverse("dashboard"), {"q": "monthly"})

        self.assertContains(response, "monthly-report.txt")


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

    def test_folder_cannot_be_moved_inside_its_child(self):
        child = Folder.objects.create(
            owner=self.user,
            parent=self.folder,
            name="Child",
        )

        response = self.client.patch(
            reverse("folder-detail", args=[self.folder.pk]),
            {"parent": child.pk},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("parent", response.json())

    def test_invalid_size_filter_returns_a_clear_error(self):
        response = self.client.get(reverse("file-list"), {"min_bytes": "large"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("min_bytes", response.json())

    def test_user_can_rename_a_folder_from_folder_page(self):
        response = self.client.post(
            reverse("folder-detail-page", args=[self.folder.pk]),
            {"action": "edit", "name": "Renamed", "parent": ""},
        )

        self.assertEqual(response.status_code, 302)
        self.folder.refresh_from_db()
        self.assertEqual(self.folder.name, "Renamed")

    def test_user_can_star_and_unstar_from_web_pages(self):
        star_response = self.client.post(
            reverse("file-star-page-action", args=[self.file_item.pk, "star"])
        )
        self.file_item.refresh_from_db()

        self.assertEqual(star_response.status_code, 302)
        self.assertTrue(self.file_item.is_starred)

        unstar_response = self.client.post(
            reverse("file-star-page-action", args=[self.file_item.pk, "unstar"]),
            {"next": "starred"},
        )
        self.file_item.refresh_from_db()

        self.assertRedirects(unstar_response, reverse("starred-page"))
        self.assertFalse(self.file_item.is_starred)

    def test_file_cannot_be_restored_before_its_folder(self):
        self.file_item.folder = self.folder
        self.file_item.save()
        Folder.objects.filter(pk=self.folder.pk).update(
            is_deleted=True,
            deleted_at=timezone.now(),
        )
        FileItem.objects.filter(pk=self.file_item.pk).update(
            is_deleted=True,
            deleted_at=timezone.now(),
        )

        response = self.client.post(
            reverse(
                "file-trash-page-action",
                args=[self.file_item.pk, "restore"],
            )
        )

        self.assertRedirects(response, reverse("trash-page"))
        self.file_item.refresh_from_db()
        self.assertTrue(self.file_item.is_deleted)

    def test_folder_api_deletes_and_restores_its_files(self):
        child = Folder.objects.create(
            owner=self.user,
            parent=self.folder,
            name="Child for trash",
        )
        self.file_item.folder = child
        self.file_item.save()
        profile = self.user.profile
        profile.used_storage_bytes = self.file_item.size_bytes
        profile.save(update_fields=["used_storage_bytes"])

        delete_response = self.client.delete(
            reverse("folder-detail", args=[self.folder.pk])
        )

        self.assertEqual(delete_response.status_code, 204)
        child.refresh_from_db()
        self.file_item.refresh_from_db()
        profile.refresh_from_db()
        self.assertTrue(child.is_deleted)
        self.assertTrue(self.file_item.is_deleted)
        self.assertEqual(profile.used_storage_bytes, 0)

        restore_response = self.client.post(
            reverse("folder-restore", args=[self.folder.pk])
        )

        self.assertEqual(restore_response.status_code, 200)
        child.refresh_from_db()
        self.file_item.refresh_from_db()
        profile.refresh_from_db()
        self.assertFalse(child.is_deleted)
        self.assertFalse(self.file_item.is_deleted)
        self.assertEqual(profile.used_storage_bytes, self.file_item.size_bytes)


class AssignmentApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="api-user", password="secret123")
        self.profile = Profile.objects.get(user=self.user)
        self.client.login(username="api-user", password="secret123")
        self.folder = Folder.objects.create(owner=self.user, name="Documents")
        self.file_item = FileItem.objects.create(
            owner=self.user,
            folder=self.folder,
            name="report.txt",
            file=SimpleUploadedFile("report.txt", b"report"),
            status=FileItem.STATUS_READY,
        )

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    def test_ajax_upload_saves_file_and_enqueues_scan(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            with patch("drive.views.scan_uploaded_file.delay") as delay:
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.post(
                        reverse("file-upload"),
                        {
                            "file": SimpleUploadedFile("new.txt", b"new content"),
                            "description": "New file",
                        },
                    )

            self.assertEqual(response.status_code, 201)
            uploaded = FileItem.objects.get(pk=response.json()["id"])
            self.assertTrue(uploaded.file.storage.exists(uploaded.file.name))
            self.assertEqual(uploaded.status, FileItem.STATUS_PROCESSING)
            self.assertTrue(
                ActivityLog.objects.filter(
                    action=ActivityLog.ACTION_UPLOAD,
                    file=uploaded,
                ).exists()
            )
            delay.assert_called_once_with(uploaded.pk)

    def test_trash_has_separate_file_and_folder_endpoints(self):
        self.file_item.is_deleted = True
        self.file_item.save()
        self.folder.is_deleted = True
        self.folder.save()

        file_response = self.client.get(reverse("trash-file-list"))
        folder_response = self.client.get(reverse("trash-folder-list"))

        self.assertEqual(file_response.status_code, 200)
        self.assertEqual(folder_response.status_code, 200)
        self.assertEqual(file_response.json()["results"][0]["id"], self.file_item.pk)
        self.assertEqual(folder_response.json()["results"][0]["id"], self.folder.pk)

    def test_create_share_link_from_file_endpoint(self):
        response = self.client.post(
            reverse("file-share-link-create", args=[self.file_item.pk]),
            {"permission": ShareLink.PERMISSION_DOWNLOAD},
        )

        self.assertEqual(response.status_code, 201)
        share_link = ShareLink.objects.get(pk=response.json()["id"])
        self.assertEqual(share_link.file, self.file_item)
        self.assertEqual(share_link.created_by, self.user)

    def test_staff_report_endpoints_require_staff(self):
        self.assertEqual(self.client.get(reverse("staff-storage-stats")).status_code, 403)

        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        storage_response = self.client.get(reverse("staff-storage-stats"))
        summary_response = self.client.get(reverse("staff-file-summary"))

        self.assertEqual(storage_response.status_code, 200)
        self.assertIn("total_storage", storage_response.json())
        self.assertEqual(summary_response.status_code, 200)
        self.assertIn("file_types", summary_response.json())

    def test_view_link_cannot_be_used_to_download(self):
        share_link = ShareLink.objects.create(
            file=self.file_item,
            created_by=self.user,
            permission=ShareLink.PERMISSION_VIEW,
        )
        self.client.logout()

        view_response = self.client.get(
            reverse("shared-file-view", args=[self.file_item.pk]),
            {"token": share_link.token},
        )
        download_response = self.client.get(
            reverse("file-download", args=[self.file_item.pk]),
            {"token": share_link.token},
        )

        self.assertEqual(view_response.status_code, 200)
        self.assertIn(download_response.status_code, {401, 403})

    def test_download_link_can_download_and_increases_counters(self):
        share_link = ShareLink.objects.create(
            file=self.file_item,
            created_by=self.user,
            permission=ShareLink.PERMISSION_DOWNLOAD,
        )
        self.client.logout()

        response = self.client.get(
            reverse("file-download", args=[self.file_item.pk]),
            {"token": share_link.token},
        )
        response.close()

        self.assertEqual(response.status_code, 200)
        self.file_item.refresh_from_db()
        share_link.refresh_from_db()
        self.assertEqual(self.file_item.download_count, 1)
        self.assertEqual(share_link.view_count, 1)

    def test_session_user_can_logout_api_without_an_existing_token(self):
        response = self.client.post(reverse("api-logout"))

        self.assertEqual(response.status_code, 204)

    def test_staff_can_view_another_users_file_but_a_regular_user_cannot(self):
        staff = User.objects.create_user(
            username="staff", password="secret123", is_staff=True
        )
        other_user = User.objects.create_user(username="other-api", password="secret123")

        self.client.logout()
        self.client.login(username="staff", password="secret123")
        staff_response = self.client.get(
            reverse("file-detail", args=[self.file_item.pk])
        )

        self.client.logout()
        self.client.login(username="other-api", password="secret123")
        user_response = self.client.get(
            reverse("file-detail", args=[self.file_item.pk])
        )

        self.assertEqual(staff_response.status_code, 200)
        self.assertIn(user_response.status_code, {403, 404})


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


class AdminActionTests(TestCase):
    def test_folder_actions_update_children_files_and_storage(self):
        user = User.objects.create_user(username="admin-action", password="secret123")
        profile = user.profile
        parent = Folder.objects.create(owner=user, name="Parent")
        child = Folder.objects.create(owner=user, parent=parent, name="Child")
        file_item = FileItem.objects.create(
            owner=user,
            folder=child,
            name="inside.txt",
            file=SimpleUploadedFile("inside.txt", b"inside"),
            status=FileItem.STATUS_READY,
        )
        profile.used_storage_bytes = file_item.size_bytes
        profile.save(update_fields=["used_storage_bytes"])
        folder_admin = FolderAdmin(Folder, admin.site)

        folder_admin.soft_delete_folders(
            None, Folder.objects.filter(pk=parent.pk)
        )

        child.refresh_from_db()
        file_item.refresh_from_db()
        profile.refresh_from_db()
        self.assertTrue(child.is_deleted)
        self.assertTrue(file_item.is_deleted)
        self.assertEqual(profile.used_storage_bytes, 0)

        folder_admin.restore_folders(None, Folder.objects.filter(pk=parent.pk))

        child.refresh_from_db()
        file_item.refresh_from_db()
        profile.refresh_from_db()
        self.assertFalse(child.is_deleted)
        self.assertFalse(file_item.is_deleted)
        self.assertEqual(profile.used_storage_bytes, file_item.size_bytes)


class SeedDriveCommandTests(TestCase):
    def test_seed_command_can_run_twice(self):
        output = StringIO()
        call_command("seed_drive", stdout=output)
        call_command("seed_drive", stdout=output)

        self.assertEqual(User.objects.filter(username__startswith="demo_").count(), 4)
        self.assertTrue(Label.objects.filter(name="Work", slug="work").exists())
        self.assertTrue(Label.objects.filter(name="Important", slug="important").exists())
        self.assertGreaterEqual(Folder.objects.count(), 3)
        self.assertGreaterEqual(FileItem.objects.count(), 3)

    def test_seed_command_reuses_an_existing_slug(self):
        Label.objects.create(name="work", slug="work")

        call_command("seed_drive", stdout=StringIO())

        self.assertEqual(Label.objects.filter(slug="work").count(), 1)
