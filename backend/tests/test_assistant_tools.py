import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from evals.fixture import EVAL_NOW

from apps.assistant.tools import AssistantContext, ToolExecutor
from apps.crm.models import Prospect, Tour

from .factories import ProspectFactory, UnitFactory

pytestmark = pytest.mark.django_db
ET = ZoneInfo("America/New_York")


@pytest.fixture
def prospect(eval_data):
    return ProspectFactory(organization=eval_data["org"])


@pytest.fixture
def ex(eval_data, prospect):
    return ToolExecutor(AssistantContext(prop=eval_data["maple"], now=EVAL_NOW, prospect=prospect))


def run(ex, name, **args):
    out, ok = ex.run(name, args)
    return json.loads(out), ok


def unit_id(eval_data, number):
    return eval_data["maple"].units.get(number=number).pk


def test_search_units_returns_live_inventory_with_filters(ex):
    out, ok = run(
        ex,
        "search_units",
        property_id=None,
        beds=2,
        min_beds=None,
        max_rent=None,
        available_by=None,
    )
    assert ok and [u["unit_number"] for u in out["units"]] == ["306", "204"]  # 305 is occupied
    assert out["units"][0]["rent"] == "$2,195/month"
    out, _ = run(
        ex,
        "search_units",
        property_id=None,
        beds=1,
        min_beds=None,
        max_rent=None,
        available_by="2026-11-15",
    )
    assert [u["unit_number"] for u in out["units"]] == ["102"]  # 203 frees up Dec 1
    out, _ = run(
        ex,
        "search_units",
        property_id=None,
        beds=None,
        min_beds=None,
        max_rent=1500,
        available_by=None,
    )
    assert [u["unit_number"] for u in out["units"]] == ["101"]


def test_search_units_never_crosses_orgs(ex, other_org):
    foreign = UnitFactory(property__organization=other_org)
    out, ok = run(
        ex,
        "search_units",
        property_id=foreign.property_id,
        beds=None,
        min_beds=None,
        max_rent=None,
        available_by=None,
    )
    assert not ok and out["error"] == "property not found"


def test_get_policy_prefers_property_specific_text(eval_data, prospect):
    birch = ToolExecutor(AssistantContext(prop=eval_data["birch"], now=EVAL_NOW))
    out, ok = run(birch, "get_policy", topic="PETS")
    assert ok and "Dogs are not allowed" in out["text"]
    out, ok = run(birch, "get_policy", topic="FEES")  # org-wide
    assert ok and "$50 per adult" in out["text"]


def test_check_tour_slots_rules(ex, eval_data):
    uid = unit_id(eval_data, "204")
    out, _ = run(ex, "check_tour_slots", unit_id=uid, date="2026-11-05")
    assert "14:00" not in out["slots"] and "14:30" in out["slots"]  # existing tour at 2pm
    assert out["slots"][0] == "09:00" and out["slots"][-1] == "16:30"
    out, _ = run(ex, "check_tour_slots", unit_id=uid, date="2026-11-08")
    assert out["slots"] == []  # Sunday
    out, _ = run(ex, "check_tour_slots", unit_id=uid, date="2026-11-02")
    assert out["slots"][0] == "11:00"  # now is 10:00 and tours need an hour's notice


def test_book_tour_creates_tour_and_advances_pipeline(ex, eval_data, prospect):
    uid = unit_id(eval_data, "204")
    out, ok = run(ex, "book_tour", prospect_id=prospect.pk, unit_id=uid, slot="2026-11-04T15:00")
    assert ok and out["booked"]
    tour = Tour.objects.get(pk=out["tour_id"])
    assert tour.start == datetime(2026, 11, 4, 15, 0, tzinfo=ET)
    assert tour.end - tour.start == timedelta(minutes=30)
    assert tour.booked_by == Tour.BookedBy.ASSISTANT and ex.booked_tour_id == tour.pk
    prospect.refresh_from_db()
    assert prospect.status == Prospect.Status.TOUR_SCHEDULED


@pytest.mark.parametrize(
    "slot",
    [
        "2026-11-05T14:00",  # already booked
        "2026-11-02T10:30",  # less than an hour away
        "2026-11-04T18:00",  # after hours
        "2026-11-04T15:10",  # not on the half hour
        "2026-11-08T11:00",  # Sunday
        "2026-10-30T11:00",  # in the past
        "tomorrow at 3",  # unparseable
    ],
)
def test_book_tour_validates_slot_server_side(ex, eval_data, prospect, slot):
    out, ok = run(
        ex, "book_tour", prospect_id=prospect.pk, unit_id=unit_id(eval_data, "204"), slot=slot
    )
    assert not ok and "error" in out
    assert not Tour.objects.filter(prospect=prospect).exists()


def test_book_tour_rejects_other_prospect_and_foreign_unit(ex, eval_data, prospect, other_org):
    someone_else = ProspectFactory(organization=eval_data["org"])
    out, ok = run(
        ex,
        "book_tour",
        prospect_id=someone_else.pk,
        unit_id=unit_id(eval_data, "204"),
        slot="2026-11-04T15:00",
    )
    assert not ok and "does not match" in out["error"]
    foreign = UnitFactory(property__organization=other_org)
    out, ok = run(
        ex, "book_tour", prospect_id=prospect.pk, unit_id=foreign.pk, slot="2026-11-04T15:00"
    )
    assert not ok and out["error"] == "unit not found"


def test_same_slot_cannot_be_booked_twice(ex, eval_data, prospect):
    args = {
        "prospect_id": prospect.pk,
        "unit_id": unit_id(eval_data, "102"),
        "slot": "2026-11-03T11:00",
    }
    assert run(ex, "book_tour", **args)[1] is True
    assert run(ex, "book_tour", **args)[1] is False


def test_draft_mode_cannot_book(eval_data, prospect):
    ex = ToolExecutor(
        AssistantContext(prop=eval_data["maple"], now=EVAL_NOW, mode="draft", prospect=prospect)
    )
    assert "book_tour" not in {t["name"] for t in ex.definitions()}
    out, ok = run(
        ex,
        "book_tour",
        prospect_id=prospect.pk,
        unit_id=unit_id(eval_data, "204"),
        slot="2026-11-04T15:00",
    )
    assert not ok and not Tour.objects.filter(prospect=prospect).exists()


def test_tool_schemas_are_strict():
    from apps.assistant.tools import TOOL_DEFS

    for tool in TOOL_DEFS:
        schema = tool["input_schema"]
        assert tool["strict"] is True and schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
