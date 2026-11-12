from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone


class AuditEvent(models.Model):
    """Append-only record of who did what, to which object, from where."""

    class Action(models.TextChoices):
        CREATE = "create"
        UPDATE = "update"
        DELETE = "delete"
        LOGIN_SUCCESS = "login_success"
        LOGIN_FAILED = "login_failed"

    # Null for failed logins and for logins to an email that has no account; those rows
    # are visible in the Django admin only.
    organization = models.ForeignKey(
        "accounts.Organization", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    # Kept so attribution survives the user being deleted; for failed logins, the email
    # that was tried.
    actor_email = models.CharField(max_length=254, blank=True)
    action = models.CharField(max_length=20, choices=Action.choices)
    object_type = models.CharField(max_length=60)
    object_id = models.CharField(max_length=64, blank=True)
    # create: {field: [null, new]}; update: changed fields {field: [old, new]};
    # delete: {field: [old, null]}.
    changes = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    ip = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-timestamp", "-id"]
        indexes = [
            models.Index(fields=["organization", "-timestamp", "-id"], name="audit_org_recent"),
            models.Index(fields=["object_type", "object_id"], name="audit_object"),
        ]

    def __str__(self):
        return (
            f"{self.timestamp:%Y-%m-%d %H:%M} {self.actor_email} {self.action} {self.object_type}"
        )

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("Audit events are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Audit events are append-only.")
