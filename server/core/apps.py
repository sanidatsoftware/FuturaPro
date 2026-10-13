from django.apps import AppConfig


class Config(AppConfig):
    name = "core"

    def ready(self):
        from . import checks  # noqa: F401
