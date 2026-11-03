import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.assistant.models import PolicyChunk
from apps.crm.models import Application, Conversation, Lease, Message, Prospect

pytestmark = pytest.mark.django_db


def test_seed_demo_is_consistent_and_never_in_the_future():
    before = timezone.now()
    # Recent leads are where follow-up timestamps could run past "now".
    call_command(
        "seed_demo",
        "--prospects",
        "300",
        "--orgs",
        "2",
        "--units-per-property",
        "20",
        "--days",
        "3",
    )
    after = timezone.now()
    assert Prospect.objects.count() == 300
    # Inbox order depends on these; anything in the future would pin stale threads on top.
    assert not Message.objects.filter(sent_at__gt=after).exists()
    assert not Conversation.objects.filter(last_message_at__gt=after).exists()
    assert not Prospect.objects.filter(last_contacted_at__gt=after).exists()
    assert not Application.objects.filter(submitted_at__gt=after).exists()
    assert not Lease.objects.filter(signed_at__gt=after).exists()
    assert Prospect.objects.filter(created_at__lt=before).count() == 300
    assert PolicyChunk.objects.exists()  # demo policies are embedded for the assistant


def test_seed_demo_refuses_to_clobber_without_reset():
    from django.core.management.base import CommandError

    call_command("seed_demo", "--prospects", "10", "--orgs", "1", "--units-per-property", "5")
    with pytest.raises(CommandError):
        call_command("seed_demo", "--prospects", "10", "--orgs", "1")
