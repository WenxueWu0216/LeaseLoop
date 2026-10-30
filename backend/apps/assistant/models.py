import uuid

from django.db import models
from pgvector.django import HnswIndex, VectorField

from apps.core.models import OrgOwnedModel, TimeStampedModel

EMBEDDING_DIM = 384


class PolicyChunk(OrgOwnedModel):
    """A retrievable slice of a PropertyPolicy, with its embedding."""

    policy = models.ForeignKey(
        "properties.PropertyPolicy", on_delete=models.CASCADE, related_name="chunks"
    )
    property = models.ForeignKey(
        "properties.Property", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    ordinal = models.PositiveSmallIntegerField()
    text = models.TextField()
    embedding = VectorField(dimensions=EMBEDDING_DIM)

    class Meta:
        indexes = [
            HnswIndex(
                name="policychunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
            models.Index(fields=["organization", "property"], name="policychunk_org_prop"),
        ]


class ChatSession(TimeStampedModel):
    """Anonymous renter chat on the public widget, tied to a prospect conversation."""

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    property = models.ForeignKey("properties.Property", on_delete=models.CASCADE, related_name="+")
    conversation = models.OneToOneField(
        "crm.Conversation", on_delete=models.CASCADE, related_name="chat_session"
    )


class AssistantRun(OrgOwnedModel):
    """One assistant turn: what it was asked, what it did, how it ended. For ops and evals."""

    class Outcome(models.TextChoices):
        ANSWERED = "ANSWERED", "Answered"
        HANDOFF = "HANDOFF", "Handed off"

    conversation = models.ForeignKey(
        "crm.Conversation", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    mode = models.CharField(max_length=10)  # chat | draft
    question = models.TextField()
    reply = models.TextField()
    outcome = models.CharField(max_length=10, choices=Outcome.choices)
    handoff_reason = models.CharField(max_length=20, blank=True)
    tools_called = models.JSONField(default=list)
    retrieval_score = models.FloatField(null=True)
    guardrail = models.CharField(max_length=40, blank=True)
    provider = models.CharField(max_length=20)
    model = models.CharField(max_length=60, blank=True)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=["organization", "-created_at"], name="assistantrun_org_created")
        ]
