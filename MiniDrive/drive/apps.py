from django.apps import AppConfig


class DriveConfig(AppConfig):
    name = "drive"

    def ready(self):
        import drive.signals
