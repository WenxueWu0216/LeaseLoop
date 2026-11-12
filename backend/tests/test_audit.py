"""Audit trail: what gets recorded, who can read it, and that it can't be rewritten."""

from unittest import mock

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Membership
from apps.audit.models import AuditEvent
from apps.crm.models import Lease, Prospect

from .factories import MembershipFactory, ProspectFactory, UnitFactory, UserFactory

pytestmark = pytest.mark.django_db
PASSWORD = "correct-horse-battery"


def events(**filters):
    return list(AuditEvent.objects.filter(**filters).order_by("id"))


# --- prospects ---------------------------------------------------------------------------


def test_prospect_create_update_delete_are_recorded(manager_client, manager, org):
    resp = manager_client.post(
        "/api/prospects/",
        {"first_name": "Ada", "last_name": "Byron", "email": "ada@example.com"},
        format="json",
        REMOTE_ADDR="198.51.100.7",
    )
    assert resp.status_code == 201
    pid = str(resp.data["id"])

    manager_client.patch(f"/api/prospects/{pid}/", {"status": "CONTACTED"}, format="json")
    manager_client.delete(f"/api/prospects/{pid}/")

    create, update, delete = events(object_type="crm.prospect", object_id=pid)
    assert (create.action, update.action, delete.action) == ("create", "update", "delete")
    for e in (create, update, delete):
        assert e.organization_id == org.pk and e.actor == manager
        assert e.actor_email == manager.email
    assert create.ip == "198.51.100.7"
    assert create.changes["first_name"] == [None, "Ada"]
    assert create.changes["email"] == [None, "ada@example.com"]
    assert "updated_at" not in create.changes and "organization_id" not in create.changes
    assert update.changes == {"status": ["NEW", "CONTACTED"]}  # only what changed
    assert delete.changes["last_name"] == ["Byron", None]


def test_no_op_update_writes_no_event(manager_client, org):
    p = ProspectFactory(organization=org, status="NEW")
    manager_client.patch(f"/api/prospects/{p.pk}/", {"status": "NEW"}, format="json")
    assert not events(object_type="crm.prospect", action="update")


def test_change_and_audit_row_commit_together(manager_client):
    failing = mock.patch("apps.audit.services.AuditEvent.objects.create", side_effect=RuntimeError)
    with failing, pytest.raises(RuntimeError):
        manager_client.post(
            "/api/prospects/", {"first_name": "Ghost", "last_name": "Row"}, format="json"
        )
    assert not Prospect.objects.filter(first_name="Ghost").exists()


def test_ip_comes_from_the_peer_not_a_spoofed_header(manager_client):
    manager_client.post(
        "/api/prospects/",
        {"first_name": "A", "last_name": "B"},
        format="json",
        REMOTE_ADDR="198.51.100.8",
        HTTP_X_FORWARDED_FOR="6.6.6.6",
    )
    assert events(action="create")[0].ip == "198.51.100.8"


# --- leases ------------------------------------------------------------------------------


def test_lease_creation_signing_and_edits_are_recorded(manager_client, manager, org, agent):
    prospect = ProspectFactory(organization=org, assigned_agent=agent, status="TOURED")
    unit = UnitFactory(property__organization=org, status="AVAILABLE")
    app_id = manager_client.post(
        "/api/applications/", {"prospect": prospect.pk, "unit": unit.pk}, format="json"
    ).data["id"]
    manager_client.post(f"/api/applications/{app_id}/submit/")
    manager_client.post(f"/api/applications/{app_id}/approve/")
    lease_id = manager_client.post(
        f"/api/applications/{app_id}/lease/",
        {"start_date": "2026-12-01", "term_months": 12},
        format="json",
    ).data["id"]
    manager_client.patch(f"/api/leases/{lease_id}/", {"monthly_rent": "1999.00"}, format="json")
    manager_client.post(f"/api/leases/{lease_id}/sign/")

    create, edit, sign = events(object_type="crm.lease", object_id=str(lease_id))
    assert create.action == "create" and create.changes["status"] == [None, "DRAFT"]
    assert create.changes["monthly_rent"][1] == str(unit.rent)
    assert edit.changes == {"monthly_rent": [str(unit.rent), "1999.00"]}
    assert sign.action == "update" and sign.changes["status"] == ["DRAFT", "SIGNED"]
    assert sign.changes["signed_at"][0] is None and sign.changes["signed_at"][1]
    assert {e.actor for e in (create, edit, sign)} == {manager}
    assert Lease.objects.get(pk=lease_id).status == "SIGNED"


# --- logins ------------------------------------------------------------------------------


@pytest.fixture
def two_org_user(org, other_org):
    user = UserFactory(email="pm@example.com")
    user.set_password(PASSWORD)
    user.save()
    MembershipFactory(user=user, organization=org, role=Membership.Role.PROPERTY_MANAGER)
    MembershipFactory(user=user, organization=other_org, role=Membership.Role.PROPERTY_MANAGER)
    return user


def login(email, password):
    return APIClient().post(
        "/api/auth/login/",
        {"email": email, "password": password},
        format="json",
        REMOTE_ADDR="203.0.113.5",
    )


def test_login_success_is_recorded_in_each_org(two_org_user, org, other_org):
    assert login(two_org_user.email, PASSWORD).status_code == 200
    rows = events(action="login_success")
    assert {r.organization_id for r in rows} == {org.pk, other_org.pk}
    assert all(r.actor == two_org_user and r.ip == "203.0.113.5" for r in rows)
    assert all(r.changes == {} for r in rows)  # nothing about the password


def test_login_failure_is_recorded_without_an_actor(two_org_user, org):
    assert login("PM@example.com", "wrong").status_code == 401
    rows = events(action="login_failed")
    assert len(rows) == 2 and all(r.actor is None for r in rows)
    assert rows[0].actor_email == "PM@example.com"
    assert rows[0].object_id == str(two_org_user.pk)


def test_failed_login_for_unknown_email_belongs_to_no_org(db):
    assert login("nobody@example.com", "x").status_code == 401
    (row,) = events(action="login_failed")
    assert row.organization_id is None and row.object_id == ""


# --- reading the trail -------------------------------------------------------------------


def test_managers_read_only_their_orgs_events(manager_client, api_for, org, other_org):
    mine = ProspectFactory(organization=org)
    manager_client.patch(f"/api/prospects/{mine.pk}/", {"notes": "called"}, format="json")
    outsider = MembershipFactory(organization=other_org, role="PROPERTY_MANAGER").user
    theirs = ProspectFactory(organization=other_org)
    api_for(outsider).patch(f"/api/prospects/{theirs.pk}/", {"notes": "x"}, format="json")
    foreign = AuditEvent.objects.get(organization=other_org, object_id=str(theirs.pk))

    resp = manager_client.get("/api/audit-events/")
    assert resp.status_code == 200
    ids = {r["object_id"] for r in resp.data["results"]}
    assert ids == {str(mine.pk)}
    assert manager_client.get(f"/api/audit-events/{foreign.pk}/").status_code == 404


def test_audit_trail_filters_by_object(manager_client, org):
    a, b = ProspectFactory(organization=org), ProspectFactory(organization=org)
    for p in (a, b):
        manager_client.patch(f"/api/prospects/{p.pk}/", {"notes": "n"}, format="json")
    resp = manager_client.get(f"/api/audit-events/?object_type=crm.prospect&object_id={a.pk}")
    assert [r["object_id"] for r in resp.data["results"]] == [str(a.pk)]


def test_agents_and_anonymous_users_cannot_read_the_trail(agent_client):
    assert agent_client.get("/api/audit-events/").status_code == 403
    assert APIClient().get("/api/audit-events/").status_code == 401


def test_trail_is_append_only(manager_client, org):
    p = ProspectFactory(organization=org)
    manager_client.patch(f"/api/prospects/{p.pk}/", {"notes": "n"}, format="json")
    event = AuditEvent.objects.get()
    for method in ("put", "patch", "delete"):
        assert getattr(manager_client, method)(f"/api/audit-events/{event.pk}/").status_code == 405
    event.changes = {"forged": True}
    with pytest.raises(RuntimeError):
        event.save()
    with pytest.raises(RuntimeError):
        event.delete()
