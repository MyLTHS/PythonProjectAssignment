from django.contrib import admin
from .models import Profile, Label, Folder, FileItem, ShareLink, ActivityLog, FileShare

admin.site.register(Profile)
admin.site.register(Label)
admin.site.register(Folder)
admin.site.register(FileItem)
admin.site.register(ShareLink)
admin.site.register(ActivityLog)
admin.site.register(FileShare)