import pytest
from django.core.management import call_command

from apps.crm.models import Conversation, Prospect, Tour

pytestmark = pytest.mark.django_db


def test_seed_prospects_bulk_creates_related_rows():
    call_command("seed_prospects", "--count", "120", "--batch-size", "50", "--org", "t-org")
    prospects = Prospect.objects.filter(organization__slug="t-org")
    assert prospects.count() == 120
    assert Conversation.objects.filter(prospect__in=prospects).count() == 120
    assert Tour.objects.filter(prospect__in=prospects).count() >= 120
    assert all(p.email.endswith("@example.com") for p in prospects)
