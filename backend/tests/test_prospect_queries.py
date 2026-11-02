"""Regression guard for the prospect-list N+1 fix.

The list returns each prospect's agent, property, tour/application counts and
next tour. If any of those is fetched per row again, the query count would
grow with the page size and these tests fail.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.crm.models import Application, Tour

from .factories import (
    MembershipFactory,
    PropertyFactory,
    ProspectFactory,
    TourFactory,
    UnitFactory,
)
from .query_count import count_queries

pytestmark = pytest.mark.django_db

# membership lookup + pagination COUNT(*) + the page itself
EXPECTED_LIST_QUERIES = 3


def add_prospects(org, n):
    """Each prospect gets its own agent, property, two tours and an application."""
    for _ in range(n):
        agent = MembershipFactory(organization=org).user
        prop = PropertyFactory(organization=org)
        unit = UnitFactory(property=prop, organization=org)
        p = ProspectFactory(organization=org, assigned_agent=agent, interested_property=prop)
        TourFactory(prospect=p, organization=org, unit=unit)
        TourFactory(
            prospect=p,
            organization=org,
            unit=unit,
            start=timezone.now() - timedelta(days=3),
            status=Tour.Status.COMPLETED,
        )
        Application.objects.create(organization=org, prospect=p, unit=unit)


def list_queries(client):
    n, resp, sql = count_queries(lambda: client.get("/api/prospects/"))
    assert resp.status_code == 200
    return n, resp.data["results"], sql


def test_prospect_list_query_count_is_constant(org, manager_client):
    add_prospects(org, 2)
    small, rows_small, _ = list_queries(manager_client)
    add_prospects(org, 20)
    large, rows_large, sql = list_queries(manager_client)

    assert (len(rows_small), len(rows_large)) == (2, 22)
    assert small == large == EXPECTED_LIST_QUERIES, "\n".join(sql)


def test_agent_prospect_list_query_count_is_constant(org, agent, agent_client):
    add_prospects(org, 2)
    ProspectFactory(organization=org, assigned_agent=agent)
    small, _, _ = list_queries(agent_client)
    for _ in range(10):
        ProspectFactory(organization=org, assigned_agent=None)
    large, rows, sql = list_queries(agent_client)

    assert len(rows) == 11
    assert small == large == EXPECTED_LIST_QUERIES, "\n".join(sql)


def test_prospect_list_related_fields(org, manager_client):
    add_prospects(org, 1)
    row = manager_client.get("/api/prospects/").data["results"][0]
    tour = Tour.objects.get(prospect_id=row["id"], status=Tour.Status.SCHEDULED)

    assert row["assigned_agent_name"]
    assert row["interested_property_name"].startswith("The Residences")
    assert row["tour_count"] == 2
    assert row["application_count"] == 1
    assert row["next_tour_at"] is not None
    assert row["next_tour_at"].startswith(tour.start.strftime("%Y-%m-%dT%H:%M"))


def test_create_response_includes_related_fields(org, manager_client):
    prop = PropertyFactory(organization=org)
    resp = manager_client.post(
        "/api/prospects/", {"first_name": "Ada", "interested_property": prop.id}, format="json"
    )
    assert resp.status_code == 201
    assert resp.data["interested_property_name"] == prop.name
    assert resp.data["tour_count"] == 0
    assert resp.data["next_tour_at"] is None
