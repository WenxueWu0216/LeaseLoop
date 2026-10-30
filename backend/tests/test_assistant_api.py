import pytest

from apps.assistant.models import ChatSession
from apps.crm.models import Conversation, HandoffTask, Message, Prospect

from .factories import ConversationFactory, MembershipFactory

pytestmark = pytest.mark.django_db


def test_chat_creates_session_and_continues_it(client, eval_data):
    prop = eval_data["maple"]
    first = client.post(
        "/api/assistant/chat/",
        {
            "property": prop.pk,
            "message": "Do you allow dogs?",
            "name": "Sam Ortiz",
            "email": "Sam@x.com",
        },
        content_type="application/json",
    )
    assert first.status_code == 200, first.json()
    body = first.json()
    assert "50" in body["reply"] and body["handoff"] is False
    prospect = Prospect.objects.get(email="sam@x.com")
    assert prospect.source == "CHAT" and prospect.first_name == "Sam"

    second = client.post(
        "/api/assistant/chat/",
        {
            "property": prop.pk,
            "session": body["session"],
            "message": "Can I talk to a real person?",
        },
        content_type="application/json",
    )
    assert second.json()["handoff"] is True
    assert ChatSession.objects.count() == 1 and Prospect.objects.filter(source="CHAT").count() == 1
    conv = Conversation.objects.get(prospect=prospect)
    assert conv.messages.count() == 4 and conv.needs_handoff
    assert HandoffTask.objects.get().reason == "REQUESTED_HUMAN"


def test_chat_session_token_is_bound_to_its_property(client, eval_data):
    a = client.post(
        "/api/assistant/chat/",
        {"property": eval_data["maple"].pk, "message": "hi"},
        content_type="application/json",
    ).json()
    client.post(
        "/api/assistant/chat/",
        {"property": eval_data["birch"].pk, "message": "hi", "session": a["session"]},
        content_type="application/json",
    )
    assert ChatSession.objects.count() == 2


def test_chat_validates_input(client, eval_data):
    resp = client.post(
        "/api/assistant/chat/",
        {"property": eval_data["maple"].pk, "message": "x" * 1001},
        content_type="application/json",
    )
    assert resp.status_code == 400
    resp = client.post(
        "/api/assistant/chat/",
        {"property": 999999, "message": "hi"},
        content_type="application/json",
    )
    assert resp.status_code == 404


def test_suggest_reply_for_agents_is_scoped_and_side_effect_free(api_for, eval_data, other_org):
    agent = eval_data["agent"]
    prospect = Prospect.objects.create(
        organization=eval_data["org"], assigned_agent=agent, interested_property=eval_data["maple"]
    )
    conv = ConversationFactory(prospect=prospect)
    Message.objects.create(
        organization=eval_data["org"],
        conversation=conv,
        direction="IN",
        channel="EMAIL",
        body="What's the pet deposit?",
        sent_at=conv.created_at,
    )
    client = api_for(agent)
    resp = client.post(f"/api/conversations/{conv.pk}/suggest-reply/")
    assert resp.status_code == 200 and "$300" in resp.json()["suggestion"]
    assert conv.messages.count() == 1  # nothing sent

    outsider = MembershipFactory(organization=other_org).user
    assert api_for(outsider).post(f"/api/conversations/{conv.pk}/suggest-reply/").status_code == 404
