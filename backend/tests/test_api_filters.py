from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.crm.models import Prospect, Tour

from .factories import (
    ConversationFactory,
    PropertyFactory,
    ProspectFactory,
    TourFactory,
    UnitFactory,
)

pytestmark = pytest.mark.django_db


def ids(resp):
    assert resp.status_code == 200, resp.data
    return {row["id"] for row in resp.data["results"]}


def test_prospect_filters(manager_client, org, agent):
    prop = PropertyFactory(organization=org)
    new = ProspectFactory(organization=org, status=Prospect.Status.NEW, assigned_agent=agent)
    toured = ProspectFactory(
        organization=org,
        status=Prospect.Status.TOURED,
        source=Prospect.Source.ZILLOW,
        interested_property=prop,
        has_pets=True,
    )
    lost = ProspectFactory(organization=org, status=Prospect.Status.LOST)

    assert ids(manager_client.get("/api/prospects/?status=NEW&status=TOURED")) == {
        new.pk,
        toured.pk,
    }
    assert ids(manager_client.get("/api/prospects/?source=ZILLOW")) == {toured.pk}
    assert ids(manager_client.get(f"/api/prospects/?assigned_agent={agent.pk}")) == {new.pk}
    assert ids(manager_client.get("/api/prospects/?unassigned=true")) == {toured.pk, lost.pk}
    assert ids(manager_client.get(f"/api/prospects/?interested_property={prop.pk}")) == {toured.pk}
    assert ids(manager_client.get("/api/prospects/?has_pets=true")) == {toured.pk}


def test_prospect_search_matches_name_email_phone(manager_client, org):
    a = ProspectFactory(organization=org, first_name="Maria", email="m@x.com", phone="5551234")
    ProspectFactory(organization=org, first_name="Bob", email="b@y.com", phone="5559999")
    for q in ("mari", "M@X", "1234"):
        assert ids(manager_client.get(f"/api/prospects/?q={q}")) == {a.pk}


def test_prospect_created_range_and_ordering(manager_client, org):
    old = ProspectFactory(organization=org)
    Prospect.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=30))
    recent = ProspectFactory(organization=org)
    cutoff = (timezone.now() - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    assert ids(manager_client.get("/api/prospects/", {"created_after": cutoff})) == {recent.pk}

    rows = manager_client.get("/api/prospects/").data["results"]
    assert [r["id"] for r in rows] == [recent.pk, old.pk]  # newest first by default
    rows = manager_client.get("/api/prospects/?ordering=created_at").data["results"]
    assert [r["id"] for r in rows] == [old.pk, recent.pk]


def test_ordering_on_unindexed_field_is_ignored(manager_client, org):
    ProspectFactory(organization=org)
    assert manager_client.get("/api/prospects/?ordering=notes").status_code == 200


def test_pagination_and_page_size_cap(manager_client, org):
    ProspectFactory.create_batch(30, organization=org)
    resp = manager_client.get("/api/prospects/")
    assert resp.data["count"] == 30 and len(resp.data["results"]) == 25 and resp.data["next"]
    resp = manager_client.get("/api/prospects/?page=2")
    assert len(resp.data["results"]) == 5 and resp.data["next"] is None
    resp = manager_client.get("/api/prospects/?page_size=1000")
    assert len(resp.data["results"]) == 30  # capped at max_page_size=100


def test_prospect_list_row_shape(manager_client, org, agent):
    prop = PropertyFactory(organization=org)
    prospect = ProspectFactory(organization=org, assigned_agent=agent, interested_property=prop)
    unit = UnitFactory(property=prop, number="4B")
    soon = TourFactory(prospect=prospect, unit=unit, start=timezone.now() + timedelta(days=1))
    TourFactory(prospect=prospect, unit=unit, start=timezone.now() + timedelta(days=3))
    TourFactory(
        prospect=prospect,
        unit=unit,
        start=timezone.now() + timedelta(hours=2),
        status=Tour.Status.CANCELED,
    )

    row = manager_client.get("/api/prospects/").data["results"][0]
    assert row["assigned_agent"]["id"] == agent.pk
    assert row["interested_property"] == {"id": prop.pk, "name": prop.name}
    assert row["next_tour"]["id"] == soon.pk and row["next_tour"]["unit_number"] == "4B"


def test_prospect_detail_includes_related(manager_client, org):
    prospect = ProspectFactory(organization=org)
    TourFactory(prospect=prospect)
    ConversationFactory(prospect=prospect)
    data = manager_client.get(f"/api/prospects/{prospect.pk}/").data
    assert len(data["tours"]) == 1 and len(data["conversations"]) == 1
    assert data["applications"] == [] and data["next_tour"] is not None


def test_write_uses_flat_ids(manager_client, org, agent):
    resp = manager_client.post(
        "/api/prospects/", {"first_name": "Ann", "assigned_agent": agent.pk}, format="json"
    )
    assert resp.status_code == 201 and resp.data["assigned_agent"] == agent.pk


def test_unit_filters(manager_client, org):
    prop = PropertyFactory(organization=org)
    cheap = UnitFactory(property=prop, beds=1, rent=Decimal("1200"))
    big = UnitFactory(
        property=prop,
        beds=3,
        rent=Decimal("2800"),
        available_from=timezone.now().date() + timedelta(days=60),
    )
    UnitFactory(property=prop, beds=2, rent=Decimal("1900"), status="OCCUPIED")
    assert ids(manager_client.get("/api/units/?beds_min=2&status=AVAILABLE")) == {big.pk}
    assert ids(manager_client.get("/api/units/?rent_max=1500")) == {cheap.pk}
    by = (timezone.now().date() + timedelta(days=7)).isoformat()
    assert big.pk not in ids(manager_client.get(f"/api/units/?available_by={by}"))


def test_tour_date_window_filter(manager_client, org):
    prospect = ProspectFactory(organization=org)
    unit = UnitFactory(property__organization=org)
    now = timezone.now()
    tomorrow = TourFactory(prospect=prospect, unit=unit, start=now + timedelta(days=1))
    TourFactory(prospect=prospect, unit=unit, start=now + timedelta(days=10))
    params = {"start_after": now.isoformat(), "start_before": (now + timedelta(days=2)).isoformat()}
    assert ids(manager_client.get("/api/tours/", params)) == {tomorrow.pk}
    assert ids(manager_client.get(f"/api/tours/?property={unit.property_id}")) == {
        t.pk for t in Tour.objects.all()
    }


def test_conversation_filters(manager_client, org):
    flagged = ConversationFactory(
        prospect=ProspectFactory(organization=org), needs_handoff=True, channel="SMS"
    )
    ConversationFactory(prospect=ProspectFactory(organization=org))
    assert ids(manager_client.get("/api/conversations/?needs_handoff=true")) == {flagged.pk}
    assert ids(manager_client.get("/api/conversations/?channel=SMS")) == {flagged.pk}
