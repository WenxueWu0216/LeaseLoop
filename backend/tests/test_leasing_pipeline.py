import pytest

from apps.crm.models import Application, Lease, Prospect
from apps.properties.models import Unit

from .factories import ProspectFactory, UnitFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def app_setup(org, agent):
    prospect = ProspectFactory(organization=org, assigned_agent=agent, status="TOURED")
    unit = UnitFactory(property__organization=org, status="AVAILABLE")
    return prospect, unit


def test_application_to_signed_lease(manager_client, app_setup):
    prospect, unit = app_setup
    resp = manager_client.post(
        "/api/applications/",
        {"prospect": prospect.pk, "unit": unit.pk, "monthly_income": "6000.00"},
        format="json",
    )
    assert resp.status_code == 201 and resp.data["status"] == "DRAFT"
    app_id = resp.data["id"]

    assert manager_client.post(f"/api/applications/{app_id}/submit/").data["status"] == "SUBMITTED"
    prospect.refresh_from_db()
    assert prospect.status == Prospect.Status.APPLIED

    assert manager_client.post(f"/api/applications/{app_id}/approve/").data["status"] == "APPROVED"
    resp = manager_client.post(
        f"/api/applications/{app_id}/lease/",
        {"start_date": "2026-12-01", "term_months": 12},
        format="json",
    )
    assert resp.status_code == 201
    lease = Lease.objects.get(pk=resp.data["id"])
    assert lease.monthly_rent == unit.rent and lease.end_date.isoformat() == "2027-12-01"

    resp = manager_client.post(f"/api/leases/{lease.pk}/sign/")
    assert resp.data["status"] == "SIGNED" and resp.data["signed_at"]
    prospect.refresh_from_db()
    unit.refresh_from_db()
    assert prospect.status == Prospect.Status.LEASED
    assert unit.status == Unit.Status.OCCUPIED and unit.available_from is None


def test_agents_can_submit_but_not_approve(agent_client, app_setup, org):
    prospect, unit = app_setup
    app = Application.objects.create(organization=org, prospect=prospect, unit=unit)
    assert agent_client.post(f"/api/applications/{app.pk}/submit/").status_code == 200
    assert agent_client.post(f"/api/applications/{app.pk}/approve/").status_code == 403
    app.refresh_from_db()
    assert app.status == Application.Status.SUBMITTED


def test_transitions_are_guarded(manager_client, app_setup, org):
    prospect, unit = app_setup
    app = Application.objects.create(organization=org, prospect=prospect, unit=unit)
    assert manager_client.post(f"/api/applications/{app.pk}/approve/").status_code == 400
    assert (
        manager_client.post(
            f"/api/applications/{app.pk}/lease/",
            {"start_date": "2026-12-01", "term_months": 12},
            format="json",
        ).status_code
        == 400
    )
    manager_client.post(f"/api/applications/{app.pk}/submit/")
    assert manager_client.post(f"/api/applications/{app.pk}/submit/").status_code == 400
    manager_client.post(f"/api/applications/{app.pk}/approve/")
    lease_url = f"/api/applications/{app.pk}/lease/"
    assert (
        manager_client.post(
            lease_url, {"start_date": "2026-12-01", "term_months": 3}, format="json"
        ).status_code
        == 400
    )  # term below 6 months
    lease_id = manager_client.post(
        lease_url, {"start_date": "2026-12-01", "term_months": 12}, format="json"
    ).data["id"]
    assert (
        manager_client.post(
            lease_url, {"start_date": "2026-12-01", "term_months": 12}, format="json"
        ).status_code
        == 400
    )  # one lease per application
    manager_client.post(f"/api/leases/{lease_id}/sign/")
    assert manager_client.post(f"/api/leases/{lease_id}/sign/").status_code == 400


def test_pipeline_actions_respect_tenancy(api_for, other_org, app_setup, org):
    from .factories import MembershipFactory

    prospect, unit = app_setup
    app = Application.objects.create(organization=org, prospect=prospect, unit=unit)
    outsider = api_for(MembershipFactory(organization=other_org, role="PROPERTY_MANAGER").user)
    assert outsider.post(f"/api/applications/{app.pk}/submit/").status_code == 404


def test_booking_a_tour_advances_new_prospects_only(manager_client, org):
    unit = UnitFactory(property__organization=org)
    fresh = ProspectFactory(organization=org, status="NEW")
    later = ProspectFactory(organization=org, status="APPLIED")
    for i, p in enumerate((fresh, later)):
        resp = manager_client.post(
            "/api/tours/",
            {
                "prospect": p.pk,
                "unit": unit.pk,
                "start": f"2030-01-0{i + 1}T15:00:00Z",
                "end": f"2030-01-0{i + 1}T15:30:00Z",
            },
            format="json",
        )
        assert resp.status_code == 201
    fresh.refresh_from_db()
    later.refresh_from_db()
    assert fresh.status == Prospect.Status.TOUR_SCHEDULED
    assert later.status == Prospect.Status.APPLIED  # never moves a prospect backwards
