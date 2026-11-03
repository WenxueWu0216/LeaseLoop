from django.apps import AppConfig


class AssistantConfig(AppConfig):
    name = "apps.assistant"

    def ready(self) -> None:
        from . import signals  # noqa: F401
