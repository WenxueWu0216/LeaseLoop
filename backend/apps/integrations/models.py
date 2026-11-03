from django.db import models

from apps.core.models import TimeStampedModel


class WebhookEvent(TimeStampedModel):
    """Idempotency ledger: one row per provider delivery, keyed by the provider's own id.

    The unique constraint is what makes duplicate deliveries harmless: the second
    insert fails, the view answers 200 and nothing is enqueued again.
    """

    class Provider(models.TextChoices):
        SENDGRID = "sendgrid", "SendGrid Inbound Parse"
        TWILIO = "twilio", "Twilio SMS"

    class Status(models.TextChoices):
        RECEIVED = "RECEIVED", "Received"
        PROCESSED = "PROCESSED", "Processed"
        IGNORED = "IGNORED", "Ignored"
        FAILED = "FAILED", "Failed"

    provider = models.CharField(max_length=20, choices=Provider.choices)
    event_id = models.CharField(max_length=255)
    organization = models.ForeignKey(
        "accounts.Organization", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    payload = models.JSONField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RECEIVED)
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["provider", "event_id"], name="uniq_webhook_event"),
        ]
        indexes = [models.Index(fields=["status", "created_at"], name="webhook_status_created")]

    def __str__(self) -> str:
        return f"{self.provider}:{self.event_id} ({self.status})"


class LeadSourceSync(TimeStampedModel):
    """Per org+source cursor for incremental ILS lead syncing."""

    organization = models.ForeignKey(
        "accounts.Organization", on_delete=models.CASCADE, related_name="+"
    )
    source = models.CharField(max_length=20)
    cursor = models.CharField(max_length=100, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "source"], name="uniq_lead_source_sync"
            ),
        ]
