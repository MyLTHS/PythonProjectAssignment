from django.contrib.auth.models import User
from django.db import models


# Create your models here.

class profile(models.Model):
    user_id = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    contact_email = models.EmailField()
    storage_quota_gb = models.PositiveIntegerField(default=0.00)
    used_storage_bytes = models.PositiveBigIntegerField(default=0)
    is_suspended = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

