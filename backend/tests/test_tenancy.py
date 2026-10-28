"""Every endpoint must hide other organizations' data (404, never 403/200)."""

import pytest

from apps.accounts.models import Membership

from .factories import (
    ConversationFactory,
    MembershipFactory,
    PropertyFactory,
    ProspectFactory,
    TourFactory,
    UnitFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def foreign(other_org):
    prospect = ProspectFactory(organization=other_org)
    unit = UnitFactory(property__organization=other_org)
    return {
        "properties": unit.property,
        "units": unit,
        "prospects": prospect,
        "tours": TourFactory(prospect=prospect, unit=unit),
        "conversations": ConversationFactory(prospect=prospect),
    }


@pytest.mark.parametrize("resource", ["properties", "units", "prospects", "tours", "conversations"])
@pytest.mark.parametrize("role", ["manager_client", "agent_client"])
def test_cross_tenant_detail_is_404(request, foreign, resource, role):
    client = request.getfixturevalue(role)
    obj = foreign[resource]
    url = f"/api/{resource}/{obj.pk}/"
    assert client.get(url).status_code == 404
    assert client.patch(url, {}, format="json").status_code == 404
    if resource != "conversations":  # conversations are not deletable at all
        assert client.delete(url).status_code == 404


@pytest.mark.parametrize("resource", ["properties", "units", "prospects", "tours"])
def test_cross_tenant_rows_absent_from_lists(manager_client, org, foreign, resource):
    PropertyFactory(organization=org)
    resp = manager_client.get(f"/api/{resource}/")
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.data["results"]}
    assert foreign[resource].pk not in ids


def test_cannot_reference_foreign_objects_on_create(manager_client, org, foreign):
    prospect = ProspectFactory(organization=org)
    resp = manager_client.post(
        "/api/tours/",
        {
            "prospect": prospect.pk,
            "unit": foreign["units"].pk,
            "start": "2030-01-01T15:00:00Z",
            "end": "2030-01-01T15:30:00Z",
        },
        format="json",
    )
    assert resp.status_code == 400
    assert "unit" in resp.data

    resp = manager_client.post(
        "/api/units/",
        {
            "property": foreign["properties"].pk,
            "number": "9",
            "beds": 1,
            "baths": "1.0",
            "rent": "1000.00",
        },
        format="json",
    )
    assert resp.status_code == 400 and "property" in resp.data


def test_cannot_assign_member_of_other_org(manager_client, other_org):
    outsider = MembershipFactory(organization=other_org).user
    resp = manager_client.post(
        "/api/prospects/", {"first_name": "Ann", "assigned_agent": outsider.pk}, format="json"
    )
    assert resp.status_code == 400 and "assigned_agent" in resp.data


def test_created_objects_get_callers_org(manager_client, org):
    resp = manager_client.post("/api/prospects/", {"first_name": "Ann"}, format="json")
    assert resp.status_code == 201
    from apps.crm.models import Prospect

    assert Prospect.objects.get(pk=resp.data["id"]).organization == org


def test_multi_org_user_selects_org_by_header(api_for, org, other_org):
    user = MembershipFactory(organization=org, role=Membership.Role.PROPERTY_MANAGER).user
    MembershipFactory(user=user, organization=other_org, role=Membership.Role.PROPERTY_MANAGER)
    mine = ProspectFactory(organization=org)
    theirs = ProspectFactory(organization=other_org)
    client = api_for(user)

    assert client.get("/api/prospects/").status_code == 403  # ambiguous without header
    resp = client.get("/api/prospects/", HTTP_X_ORGANIZATION=str(other_org.pk))
    assert [r["id"] for r in resp.data["results"]] == [theirs.pk]
    resp = client.get("/api/prospects/", HTTP_X_ORGANIZATION=str(org.pk))
    assert [r["id"] for r in resp.data["results"]] == [mine.pk]


def test_header_for_org_user_does_not_belong_to_is_404(agent_client, other_org):
    resp = agent_client.get("/api/prospects/", HTTP_X_ORGANIZATION=str(other_org.pk))
    assert resp.status_code == 404


def test_user_without_membership_is_forbidden(api_for):
    from .factories import UserFactory

    assert api_for(UserFactory()).get("/api/prospects/").status_code == 403


def test_anonymous_is_rejected(client):
    assert client.get("/api/prospects/").status_code in (401, 403)
