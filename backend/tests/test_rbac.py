import pytest

from apps.accounts.models import Membership

from .factories import (
    ConversationFactory,
    PropertyFactory,
    ProspectFactory,
    TourFactory,
    UnitFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def prospects(org, agent, other_agent):
    return {
        "mine": ProspectFactory(organization=org, assigned_agent=agent),
        "unassigned": ProspectFactory(organization=org, assigned_agent=None),
        "theirs": ProspectFactory(organization=org, assigned_agent=other_agent),
    }


# --- properties & units: managers write, agents read ---


def test_manager_can_manage_properties_and_units(manager_client):
    resp = manager_client.post(
        "/api/properties/",
        {
            "name": "Elm",
            "address": "1 Elm St",
            "city": "Austin",
            "state": "TX",
            "zip_code": "78701",
        },
        format="json",
    )
    assert resp.status_code == 201
    prop_id = resp.data["id"]
    resp = manager_client.post(
        "/api/units/",
        {"property": prop_id, "number": "1A", "beds": 2, "baths": "1.5", "rent": "2100.00"},
        format="json",
    )
    assert resp.status_code == 201
    assert (
        manager_client.patch(
            f"/api/units/{resp.data['id']}/", {"rent": "2000.00"}, format="json"
        ).status_code
        == 200
    )


def test_agent_reads_but_cannot_write_properties_or_units(agent_client, org):
    unit = UnitFactory(property__organization=org)
    assert agent_client.get("/api/properties/").status_code == 200
    assert agent_client.get(f"/api/units/{unit.pk}/").status_code == 200
    assert agent_client.post("/api/properties/", {"name": "X"}, format="json").status_code == 403
    assert (
        agent_client.patch(f"/api/units/{unit.pk}/", {"rent": "1.00"}, format="json").status_code
        == 403
    )
    assert agent_client.delete(f"/api/properties/{unit.property.pk}/").status_code == 403


def test_only_managers_manage_team(manager_client, agent_client):
    assert agent_client.get("/api/memberships/").status_code == 403
    resp = manager_client.post(
        "/api/memberships/", {"email": "new@agent.com", "role": "LEASING_AGENT"}, format="json"
    )
    assert resp.status_code == 201
    assert (
        agent_client.post(
            "/api/memberships/", {"email": "x@y.com", "role": "PROPERTY_MANAGER"}, format="json"
        ).status_code
        == 403
    )


# --- prospects: agents see their own + unassigned ---


def test_manager_sees_all_prospects(manager_client, prospects):
    ids = {r["id"] for r in manager_client.get("/api/prospects/").data["results"]}
    assert ids == {p.pk for p in prospects.values()}


def test_agent_sees_only_own_and_unassigned(agent_client, prospects):
    ids = {r["id"] for r in agent_client.get("/api/prospects/").data["results"]}
    assert ids == {prospects["mine"].pk, prospects["unassigned"].pk}
    assert agent_client.get(f"/api/prospects/{prospects['theirs'].pk}/").status_code == 404
    assert (
        agent_client.patch(
            f"/api/prospects/{prospects['theirs'].pk}/", {"notes": "x"}, format="json"
        ).status_code
        == 404
    )


def test_agent_can_claim_unassigned_but_not_assign_to_others(
    agent_client, agent, other_agent, prospects
):
    url = f"/api/prospects/{prospects['unassigned'].pk}/"
    assert (
        agent_client.patch(url, {"assigned_agent": other_agent.pk}, format="json").status_code
        == 400
    )
    resp = agent_client.patch(url, {"assigned_agent": agent.pk}, format="json")
    assert resp.status_code == 200 and resp.data["assigned_agent"] == agent.pk


def test_manager_can_reassign(manager_client, other_agent, prospects):
    resp = manager_client.patch(
        f"/api/prospects/{prospects['mine'].pk}/", {"assigned_agent": other_agent.pk}, format="json"
    )
    assert resp.status_code == 200 and resp.data["assigned_agent"] == other_agent.pk


def test_agent_conversations_follow_prospect_visibility(agent_client, prospects):
    visible = ConversationFactory(prospect=prospects["mine"])
    hidden = ConversationFactory(prospect=prospects["theirs"])
    ids = {r["id"] for r in agent_client.get("/api/conversations/").data["results"]}
    assert visible.pk in ids and hidden.pk not in ids


# --- tours ---


def test_agent_sees_only_own_and_unassigned_tours(agent_client, org, agent, other_agent, prospects):
    mine = TourFactory(
        prospect=prospects["mine"], agent=agent, unit=UnitFactory(property__organization=org)
    )
    open_tour = TourFactory(
        prospect=prospects["unassigned"], agent=None, unit=UnitFactory(property__organization=org)
    )
    theirs = TourFactory(
        prospect=prospects["theirs"],
        agent=other_agent,
        unit=UnitFactory(property__organization=org),
    )
    ids = {r["id"] for r in agent_client.get("/api/tours/").data["results"]}
    assert ids == {mine.pk, open_tour.pk}
    assert (
        agent_client.patch(f"/api/tours/{theirs.pk}/", {"notes": "x"}, format="json").status_code
        == 404
    )
    assert (
        agent_client.patch(
            f"/api/tours/{mine.pk}/", {"notes": "bring keys"}, format="json"
        ).status_code
        == 200
    )


def test_agent_cannot_book_tour_for_hidden_prospect(agent_client, org, prospects):
    unit = UnitFactory(property__organization=org)
    payload = {"unit": unit.pk, "start": "2030-01-01T15:00:00Z", "end": "2030-01-01T15:30:00Z"}
    resp = agent_client.post(
        "/api/tours/", {**payload, "prospect": prospects["theirs"].pk}, format="json"
    )
    assert resp.status_code == 400 and "prospect" in resp.data
    resp = agent_client.post(
        "/api/tours/", {**payload, "prospect": prospects["mine"].pk}, format="json"
    )
    assert resp.status_code == 201


def test_tour_end_must_follow_start(manager_client, org):
    prospect = ProspectFactory(organization=org)
    unit = UnitFactory(property=PropertyFactory(organization=org))
    resp = manager_client.post(
        "/api/tours/",
        {
            "prospect": prospect.pk,
            "unit": unit.pk,
            "start": "2030-01-01T15:00:00Z",
            "end": "2030-01-01T14:00:00Z",
        },
        format="json",
    )
    assert resp.status_code == 400 and "end" in resp.data


def test_me_endpoint_lists_memberships(agent_client, org):
    data = agent_client.get("/api/auth/me/").data
    assert data["memberships"] == [
        {
            "organization": {"id": org.pk, "name": org.name, "slug": org.slug},
            "role": Membership.Role.LEASING_AGENT,
        }
    ]


def test_token_login(client, agent):
    resp = client.post("/api/auth/login/", {"username": agent.email, "password": "pass1234!"})
    assert resp.status_code == 200 and resp.json()["token"]
