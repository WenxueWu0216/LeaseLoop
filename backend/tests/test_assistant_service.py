import pytest
from evals.fixture import EVAL_NOW

from apps.assistant.models import AssistantRun, PolicyChunk
from apps.assistant.providers import AssistantUnavailable, LLMTurn, ToolCall
from apps.assistant.retrieval import search
from apps.assistant.service import Assistant
from apps.assistant.tools import AssistantContext
from apps.crm.models import Channel, Conversation, HandoffTask, Message, Prospect

pytestmark = pytest.mark.django_db


class Scripted:
    """Provider that replays canned turns, to drive the service deterministically."""

    name = "scripted"

    def __init__(self, *turns):
        self.turns = list(turns)
        self.seen: list[list] = []

    def run(self, system, messages, tools):
        self.seen.append(list(messages))
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn


def call(name, **args):
    block = {"type": "tool_use", "id": f"t_{name}", "name": name, "input": args}
    return LLMTurn(
        text="",
        tool_calls=[ToolCall(block["id"], name, args)],
        content=[block],
        stop_reason="tool_use",
    )


def text(t, stop="end_turn"):
    return LLMTurn(text=t, tool_calls=[], content=[{"type": "text", "text": t}], stop_reason=stop)


SEARCH = {"property_id": None, "beds": 1, "min_beds": None, "max_rent": None, "available_by": None}


@pytest.fixture
def chat(eval_data):
    prospect = Prospect.objects.create(
        organization=eval_data["org"], first_name="Ana", interested_property=eval_data["maple"]
    )
    conv = Conversation.objects.create(
        organization=eval_data["org"], prospect=prospect, channel=Channel.CHAT
    )
    return AssistantContext(
        prop=eval_data["maple"], now=EVAL_NOW, prospect=prospect, conversation=conv
    )


def test_grounded_answer_is_sent_and_logged(chat):
    provider = Scripted(call("search_units", **SEARCH), text("Unit 102 is $1,725/month."))
    reply = Assistant(provider).respond(chat, "How much is a one bedroom?")
    assert not reply.handed_off and reply.text == "Unit 102 is $1,725/month."
    msg = Message.objects.get(conversation=chat.conversation)
    assert msg.is_assistant and msg.direction == "OUT"
    run = AssistantRun.objects.get()
    assert run.outcome == "ANSWERED" and run.tools_called[0]["name"] == "search_units"
    # The tool result went back to the model in the same turn.
    assert provider.seen[1][-1]["content"][0]["type"] == "tool_result"


def test_ungrounded_price_is_blocked_and_handed_off(chat):
    provider = Scripted(call("search_units", **SEARCH), text("Unit 102 is $1,499/month!"))
    reply = Assistant(provider).respond(chat, "How much is a one bedroom?")
    assert reply.handoff_reason == "UNGROUNDED" and reply.guardrail == "ungrounded price"
    assert "$1,499" not in reply.text and reply.draft_text == "Unit 102 is $1,499/month!"
    task = HandoffTask.objects.get()
    assert task.reason == "UNGROUNDED" and task.question == "How much is a one bedroom?"
    chat.conversation.refresh_from_db()
    assert chat.conversation.needs_handoff


def test_price_without_any_tool_call_is_blocked(chat):
    reply = Assistant(Scripted(text("Our 1 beds are $1,725."))).respond(chat, "1 bed price?")
    # $1,725 is real, but nothing in this turn sourced it, so it doesn't pass.
    assert reply.handed_off


def test_answer_with_no_grounding_source_is_low_confidence(chat):
    reply = Assistant(Scripted(text("Yes, we have a sauna."))).respond(chat, "Is there a sauna?")
    assert reply.handoff_reason == "LOW_CONFIDENCE"


def test_model_requested_handoff(chat):
    provider = Scripted(call("handoff_to_human", reason="unsure", summary="no info"))
    reply = Assistant(provider).respond(chat, "Can I install a hot tub on my balcony?")
    assert reply.handoff_reason == "MODEL_UNSURE"
    assert HandoffTask.objects.filter(reason="MODEL_UNSURE").exists()


def test_prefilter_hands_off_without_calling_the_model(chat):
    provider = Scripted()
    reply = Assistant(provider).respond(chat, "Is this building good for families with kids?")
    assert reply.handoff_reason == "FAIR_HOUSING" and provider.seen == []
    assert "fair housing" in reply.text


@pytest.mark.parametrize(
    "turn,reason",
    [
        (text("", stop="refusal"), "MODEL_UNSURE"),
        (text("Unit 102 is", stop="max_tokens"), "MODEL_UNSURE"),
        (AssistantUnavailable("overloaded"), "ASSISTANT_ERROR"),
    ],
)
def test_refusal_truncation_and_outage_hand_off(chat, turn, reason):
    reply = Assistant(Scripted(turn)).respond(chat, "What's the rent on a studio?")
    assert reply.handoff_reason == reason


def test_step_limit_hands_off(chat):
    loop = [call("search_units", **SEARCH) for _ in range(6)]
    reply = Assistant(Scripted(*loop)).respond(chat, "rent?")
    assert reply.handoff_reason == "MODEL_UNSURE" and reply.guardrail == "step limit"


def test_draft_mode_has_no_side_effects(chat):
    chat.mode = "draft"
    reply = Assistant(Scripted(text("Sounds good"))).respond(chat, "Is there a sauna?")
    assert reply.handed_off
    assert not HandoffTask.objects.exists() and not Message.objects.exists()
    assert AssistantRun.objects.get().mode == "draft"


def test_mock_provider_books_a_tour_end_to_end(chat):
    from apps.assistant.mock_provider import MockProvider

    reply = Assistant(MockProvider()).respond(chat, "Can I tour unit 204 on Wednesday at 3pm?")
    assert reply.booked_tour_id and "booked" in reply.text.lower()
    assert [c["name"] for c in reply.tools_called] == [
        "search_units",
        "check_tour_slots",
        "book_tour",
    ]


def test_retrieval_scopes_to_property_and_org(eval_data, other_org):
    from apps.properties.models import PropertyPolicy

    from .factories import PropertyFactory

    PropertyPolicy.objects.create(
        organization=other_org,
        property=PropertyFactory(organization=other_org),
        topic="PETS",
        title="Pets",
        body="Dogs of any size, $9 rent.",
    )
    hits = search(eval_data["birch"], "are dogs allowed", k=10)
    texts = " ".join(h.text for h in hits)
    assert "Dogs are not allowed at Birch Lofts" in texts
    assert "under 50 lbs" not in texts and "$9" not in texts  # Maple's and other org's


def test_policy_edits_are_reindexed(eval_data, django_capture_on_commit_callbacks):
    policy = eval_data["maple"].policies.get(topic="PETS")
    with django_capture_on_commit_callbacks(execute=True):
        policy.body = "Only cats are allowed. The pet deposit is $400."
        policy.save()
    chunks = PolicyChunk.objects.filter(policy=policy)
    assert chunks.count() == 1 and "$400" in chunks.get().text
