import re
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Q
from pgvector.django import CosineDistance

from apps.properties.models import Property, PropertyPolicy

from .embeddings import get_embedder
from .models import PolicyChunk

SENTENCE = re.compile(r"(?<=[.!?])\s+")
MAX_CHARS = 320


def chunk_policy(policy: PropertyPolicy) -> list[str]:
    """Sentence-packed chunks of ~MAX_CHARS, each prefixed with the policy title.

    The title header keeps short chunks ("$35/month per pet.") attributable to their
    topic for both retrieval and the model reading them.
    """
    sentences = [s.strip() for s in SENTENCE.split(policy.body) if s.strip()]
    chunks, current = [], ""
    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > MAX_CHARS:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return [f"{policy.title}: {c}" for c in chunks]


@transaction.atomic
def index_policy(policy: PropertyPolicy) -> int:
    embedder = get_embedder()
    PolicyChunk.objects.filter(policy=policy).delete()
    rows = [
        PolicyChunk(
            organization_id=policy.organization_id,
            policy=policy,
            property_id=policy.property_id,
            ordinal=i,
            text=text,
            embedding=embedder.embed(text),
        )
        for i, text in enumerate(chunk_policy(policy))
    ]
    PolicyChunk.objects.bulk_create(rows)
    return len(rows)


@dataclass(frozen=True)
class Retrieved:
    text: str
    topic: str
    score: float  # cosine similarity, 1.0 = identical


def search(prop: Property, query: str, k: int = 4) -> list[Retrieved]:
    """Top-k chunks for this property: its own policies plus org-wide ones."""
    qvec = get_embedder().embed(query)
    rows = (
        PolicyChunk.objects.filter(organization_id=prop.organization_id)
        .filter(Q(property=prop) | Q(property__isnull=True))
        .select_related("policy")
        .annotate(distance=CosineDistance("embedding", qvec))
        .order_by("distance")[:k]
    )
    return [Retrieved(text=r.text, topic=r.policy.topic, score=1 - r.distance) for r in rows]
