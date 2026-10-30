from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.core.models import OrgOwnedModel


class Channel(models.TextChoices):
    EMAIL = "EMAIL", "Email"
    SMS = "SMS", "SMS"
    CHAT = "CHAT", "Chat"


class Prospect(OrgOwnedModel):
    class Source(models.TextChoices):
        WEBSITE = "WEBSITE", "Website"
        EMAIL = "EMAIL", "Email"
        SMS = "SMS", "SMS"
        CHAT = "CHAT", "Chat widget"
        ZILLOW = "ZILLOW", "Zillow"
        APARTMENTS_COM = "APARTMENTS_COM", "Apartments.com"
        WALK_IN = "WALK_IN", "Walk-in"
        REFERRAL = "REFERRAL", "Referral"

    class Status(models.TextChoices):
        NEW = "NEW", "New"
        CONTACTED = "CONTACTED", "Contacted"
        TOUR_SCHEDULED = "TOUR_SCHEDULED", "Tour scheduled"
        TOURED = "TOURED", "Toured"
        APPLIED = "APPLIED", "Applied"
        APPROVED = "APPROVED", "Approved"
        LEASED = "LEASED", "Leased"
        LOST = "LOST", "Lost"

    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.WEBSITE)
    # Identifier in the upstream lead source (ILS listing lead id), for idempotent sync.
    external_id = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    assigned_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_prospects",
    )
    interested_property = models.ForeignKey(
        "properties.Property",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="prospects",
    )
    desired_move_in = models.DateField(null=True, blank=True)
    beds_min = models.PositiveSmallIntegerField(null=True, blank=True)
    budget_max = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    has_pets = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    last_contacted_at = models.DateTimeField(null=True, blank=True)
    last_followup_at = models.DateTimeField(null=True, blank=True)
    followup_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "source", "external_id"],
                condition=~Q(external_id=""),
                name="uniq_prospect_external_id",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "status", "-created_at"], name="prospect_org_status_created"
            ),
            models.Index(fields=["organization", "-created_at"], name="prospect_org_created"),
            models.Index(
                fields=["organization", "assigned_agent", "status"],
                name="prospect_org_agent_status",
            ),
            models.Index(fields=["organization", "email"], name="prospect_org_email"),
            models.Index(fields=["organization", "phone"], name="prospect_org_phone"),
        ]

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() or self.email or self.phone

    def __str__(self) -> str:
        return self.full_name


class Conversation(OrgOwnedModel):
    """One thread per prospect+channel; drives the unified inbox."""

    prospect = models.ForeignKey(Prospect, on_delete=models.CASCADE, related_name="conversations")
    channel = models.CharField(max_length=10, choices=Channel.choices)
    subject = models.CharField(max_length=255, blank=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    is_unread = models.BooleanField(default=True)
    needs_handoff = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["prospect", "channel"], name="uniq_conversation_channel"
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "-last_message_at"], name="conversation_org_last_msg"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.prospect} ({self.channel})"


class Message(OrgOwnedModel):
    class Direction(models.TextChoices):
        INBOUND = "IN", "Inbound"
        OUTBOUND = "OUT", "Outbound"

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    direction = models.CharField(max_length=3, choices=Direction.choices)
    channel = models.CharField(max_length=10, choices=Channel.choices)
    body = models.TextField()
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    is_assistant = models.BooleanField(default=False)
    # e.g. "sendgrid"/"twilio" + their message id; enforces at-most-once ingestion.
    provider = models.CharField(max_length=20, blank=True)
    provider_message_id = models.CharField(max_length=255, blank=True)
    sent_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_message_id"],
                condition=~Q(provider_message_id=""),
                name="uniq_message_provider_id",
            ),
        ]
        indexes = [models.Index(fields=["conversation", "sent_at"], name="message_conv_sent")]


class Tour(OrgOwnedModel):
    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Scheduled"
        COMPLETED = "COMPLETED", "Completed"
        CANCELED = "CANCELED", "Canceled"
        NO_SHOW = "NO_SHOW", "No-show"

    class BookedBy(models.TextChoices):
        AGENT = "AGENT", "Agent"
        ASSISTANT = "ASSISTANT", "Assistant"
        PROSPECT = "PROSPECT", "Prospect"

    prospect = models.ForeignKey(Prospect, on_delete=models.CASCADE, related_name="tours")
    unit = models.ForeignKey("properties.Unit", on_delete=models.CASCADE, related_name="tours")
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tours",
    )
    start = models.DateTimeField()
    end = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCHEDULED)
    booked_by = models.CharField(max_length=12, choices=BookedBy.choices, default=BookedBy.AGENT)
    notes = models.TextField(blank=True)
    reminder_24h_sent_at = models.DateTimeField(null=True, blank=True)
    reminder_1h_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(end__gt=F("start")), name="tour_end_after_start"),
        ]
        indexes = [
            models.Index(fields=["organization", "start"], name="tour_org_start"),
            models.Index(fields=["agent", "start"], name="tour_agent_start"),
            models.Index(fields=["unit", "start"], name="tour_unit_start"),
            models.Index(fields=["status", "start"], name="tour_status_start"),
        ]


class Application(OrgOwnedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        SCREENING = "SCREENING", "Screening"
        APPROVED = "APPROVED", "Approved"
        DENIED = "DENIED", "Denied"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"

    prospect = models.ForeignKey(Prospect, on_delete=models.CASCADE, related_name="applications")
    unit = models.ForeignKey(
        "properties.Unit", on_delete=models.PROTECT, related_name="applications"
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    monthly_income = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    desired_move_in = models.DateField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["organization", "status"], name="application_org_status")]


class ApplicationDocument(OrgOwnedModel):
    class Kind(models.TextChoices):
        ID = "ID", "Photo ID"
        PAYSTUB = "PAYSTUB", "Pay stub"
        BANK_STATEMENT = "BANK_STATEMENT", "Bank statement"
        OTHER = "OTHER", "Other"

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="documents")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    file = models.FileField(upload_to="applications/%Y/%m/")


class Lease(OrgOwnedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SENT = "SENT", "Sent for signature"
        SIGNED = "SIGNED", "Signed"
        ACTIVE = "ACTIVE", "Active"
        ENDED = "ENDED", "Ended"

    application = models.OneToOneField(
        Application, on_delete=models.SET_NULL, null=True, blank=True, related_name="lease"
    )
    prospect = models.ForeignKey(Prospect, on_delete=models.PROTECT, related_name="leases")
    unit = models.ForeignKey("properties.Unit", on_delete=models.PROTECT, related_name="leases")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    start_date = models.DateField()
    end_date = models.DateField()
    term_months = models.PositiveSmallIntegerField()
    monthly_rent = models.DecimalField(max_digits=8, decimal_places=2)
    signed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gt=F("start_date")), name="lease_end_after_start"
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "status", "end_date"], name="lease_org_status_end"
            ),
        ]


class Renewal(OrgOwnedModel):
    class Status(models.TextChoices):
        OFFERED = "OFFERED", "Offered"
        ACCEPTED = "ACCEPTED", "Accepted"
        DECLINED = "DECLINED", "Declined"
        EXPIRED = "EXPIRED", "Expired"

    lease = models.ForeignKey(Lease, on_delete=models.CASCADE, related_name="renewals")
    offered_rent = models.DecimalField(max_digits=8, decimal_places=2)
    term_months = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OFFERED)
    offer_expires_on = models.DateField()
    responded_at = models.DateTimeField(null=True, blank=True)


class HandoffTask(OrgOwnedModel):
    """Created when the assistant declines to answer; surfaces in the inbox."""

    class Reason(models.TextChoices):
        LOW_CONFIDENCE = "LOW_CONFIDENCE", "Low retrieval confidence"
        OUT_OF_SCOPE = "OUT_OF_SCOPE", "Out of scope"
        FAIR_HOUSING = "FAIR_HOUSING", "Fair-housing sensitive"
        MODEL_UNSURE = "MODEL_UNSURE", "Model unsure"
        REQUESTED_HUMAN = "REQUESTED_HUMAN", "Renter asked for a human"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        RESOLVED = "RESOLVED", "Resolved"

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="handoffs"
    )
    prospect = models.ForeignKey(Prospect, on_delete=models.CASCADE, related_name="handoffs")
    reason = models.CharField(max_length=20, choices=Reason.choices)
    question = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["organization", "status"], name="handoff_org_status")]
