from datetime import timedelta

import pytest
from django.utils import timezone

from apps.crm.models import HandoffTask, Message, Prospect

from .factories import ConversationFactory, ProspectFactory, TourFactory, UnitFactory

pytestmark = pytest.mark.django_db


def add_message(conv, body, direction="IN", minutes=0, **kw):
    return Message.objects.create(
        organization=conv.organization,
        conversation=conv,
        direction=direction,
        channel=conv.channel,
        body=body,
        sent_at=timezone.now() + timedelta(minutes=minutes),
        **kw,
    )


def test_inbox_rows_show_last_message_and_open_handoffs(manager_client, org):
    conv = ConversationFactory(
        prospect=ProspectFactory(organization=org, first_name="Rita"), needs_handoff=True
    )
    add_message(conv, "first")
    add_message(conv, "Is parking included?", minutes=5)
    HandoffTask.objects.create(
        organization=org,
        conversation=conv,
        prospect=conv.prospect,
        reason="OUT_OF_SCOPE",
        question="q",
    )
    HandoffTask.objects.create(
        organization=org,
        conversation=conv,
        prospect=conv.prospect,
        reason="OUT_OF_SCOPE",
        question="q2",
        status="RESOLVED",
    )
    row = manager_client.get("/api/conversations/").data["results"][0]
    assert row["prospect"]["name"].startswith("Rita")
    assert row["last_message"] == {
        "body": "Is parking included?",
        "direction": "IN",
        "is_assistant": False,
    }
    assert row["open_handoffs"] == 1 and row["needs_handoff"] is True


@pytest.mark.parametrize("n", [1, 20])
def test_inbox_query_count_is_constant(manager_client, org, n, django_assert_num_queries):
    for i in range(n):
        conv = ConversationFactory(prospect=ProspectFactory(organization=org))
        add_message(conv, f"hello {i}")
    # membership + COUNT + page (annotations are subqueries in the same statement)
    with django_assert_num_queries(3):
        assert len(manager_client.get("/api/conversations/").data["results"]) == n


def test_agent_reply_is_sent_and_updates_pipeline(agent_client, agent, org, outbox):
    prospect = ProspectFactory(organization=org, assigned_agent=agent, phone="+12015550111")
    conv = ConversationFactory(prospect=prospect, channel="SMS", is_unread=True)
    add_message(conv, "Hi, is the 1 bed available?")
    resp = agent_client.post(
        f"/api/conversations/{conv.pk}/messages/", {"body": "Yes! Want to tour?"}, format="json"
    )
    assert resp.status_code == 200
    assert [m["direction"] for m in resp.data] == ["IN", "OUT"]
    out = Message.objects.get(direction="OUT")
    assert out.sender == agent and out.channel == "SMS"
    assert outbox[0].to == "+12015550111" and outbox[0].idempotency_key == f"message:{out.pk}"
    prospect.refresh_from_db()
    conv.refresh_from_db()
    assert prospect.status == Prospect.Status.CONTACTED and prospect.last_contacted_at
    assert conv.is_unread is False


def test_agent_cannot_read_or_reply_to_hidden_conversation(agent_client, org, other_agent):
    conv = ConversationFactory(
        prospect=ProspectFactory(organization=org, assigned_agent=other_agent)
    )
    url = f"/api/conversations/{conv.pk}/messages/"
    assert agent_client.get(url).status_code == 404
    assert agent_client.post(url, {"body": "hi"}, format="json").status_code == 404


def test_calendar_rows_include_names(manager_client, org):
    tour = TourFactory(
        prospect=ProspectFactory(organization=org, first_name="Lee", last_name="Park"),
        unit=UnitFactory(property__organization=org, number="4C"),
    )
    row = manager_client.get("/api/tours/").data["results"][0]
    assert row["id"] == tour.pk and row["prospect_name"] == "Lee Park"
    assert row["unit_number"] == "4C" and row["property_name"] == tour.unit.property.name


def test_reschedule_rejects_overlap_and_allows_free_slot(manager_client, org):
    unit = UnitFactory(property__organization=org)
    start = timezone.now().replace(microsecond=0) + timedelta(days=2)
    busy = TourFactory(prospect=ProspectFactory(organization=org), unit=unit, start=start)
    moving = TourFactory(
        prospect=ProspectFactory(organization=org), unit=unit, start=start + timedelta(hours=2)
    )
    url = f"/api/tours/{moving.pk}/"
    clash = {
        "start": (start + timedelta(minutes=15)).isoformat(),
        "end": (start + timedelta(minutes=45)).isoformat(),
    }
    resp = manager_client.patch(url, clash, format="json")
    assert resp.status_code == 400 and "start" in resp.data
    free = {
        "start": (start + timedelta(hours=1)).isoformat(),
        "end": (start + timedelta(hours=1, minutes=30)).isoformat(),
    }
    assert manager_client.patch(url, free, format="json").status_code == 200
    # A tour may be edited in place without clashing with itself.
    assert (
        manager_client.patch(f"/api/tours/{busy.pk}/", {"notes": "x"}, format="json").status_code
        == 200
    )


def test_tour_list_query_count_is_constant(manager_client, org, django_assert_num_queries):
    unit = UnitFactory(property__organization=org)
    for i in range(10):
        TourFactory(
            prospect=ProspectFactory(organization=org),
            unit=unit,
            start=timezone.now() + timedelta(days=1, hours=i),
        )
    with django_assert_num_queries(3):
        manager_client.get("/api/tours/")
