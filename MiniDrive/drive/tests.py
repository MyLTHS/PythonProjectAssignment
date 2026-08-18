from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from .models import FileItem, FileShare, ShareLink


class ShareLinkModelTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="secret123")
        self.file_item = FileItem(
            owner=self.owner,
            name="Guide",
            external_url="https://example.com/guide.pdf",
            status=FileItem.STATUS_READY,
        )
        self.file_item.save()

    def test_share_link_generates_token_on_save(self):
        share_link = ShareLink(file=self.file_item, created_by=self.owner)

        share_link.save()

        self.assertTrue(share_link.token)

    def test_share_link_rejects_deleted_file(self):
        self.file_item.is_deleted = True
        self.file_item.deleted_at = timezone.now()
        self.file_item.save()
        share_link = ShareLink(file=self.file_item, created_by=self.owner)

        with self.assertRaises(ValidationError):
            share_link.full_clean()

    def test_share_link_rejects_past_expiration(self):
        share_link = ShareLink(
            file=self.file_item,
            created_by=self.owner,
            expires_at=timezone.now() - timedelta(days=1),
        )

        with self.assertRaises(ValidationError):
            share_link.full_clean()


class FileShareModelTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner2", password="secret123")
        self.viewer = User.objects.create_user(username="viewer2", password="secret123")
        self.other_user = User.objects.create_user(
            username="other2",
            password="secret123",
        )
        self.file_item = FileItem(
            owner=self.owner,
            name="Roadmap",
            external_url="https://example.com/roadmap.pdf",
            status=FileItem.STATUS_READY,
        )
        self.file_item.save()

    def test_file_share_requires_shared_by_to_be_owner(self):
        file_share = FileShare(
            file=self.file_item,
            shared_by=self.other_user,
            shared_with=self.viewer,
        )

        with self.assertRaises(ValidationError):
            file_share.full_clean()
