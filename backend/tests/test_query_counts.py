"""Guards against N+1 regressions: query count must not grow with page size."""

from datetime import timedelta

import pytest
from django.utils import timezone

from .factories import (
    ConversationFactory,
    PropertyFactory,
    ProspectFactory,
    TourFactory,
    UnitFactory,
)

pytestmark = pytest.mark.django_db

# membership + COUNT + page + upcoming-tours prefetch (force_authenticate skips the token lookup)
LIST_QUERIES = 4


def make_prospects(org, agent, n):
    prop = PropertyFactory(organization=org)
    unit = UnitFactory(property=prop)
    for _ in range(n):
        p = ProspectFactory(organization=org, assigned_agent=agent, interested_property=prop)
        TourFactory(prospect=p, unit=unit, start=timezone.now() + timedelta(days=1))
        ConversationFactory(prospect=p)


@pytest.mark.parametrize("rows", [1, 25])
def test_prospect_list_query_count_is_constant(
    manager_client, org, agent, rows, django_assert_num_queries
):
    make_prospects(org, agent, rows)
    with django_assert_num_queries(LIST_QUERIES):
        resp = manager_client.get("/api/prospects/")
    assert len(resp.data["results"]) == rows
    assert all(r["next_tour"] and r["assigned_agent"] for r in resp.data["results"])


def test_prospect_detail_query_count(manager_client, org, agent, django_assert_num_queries):
    make_prospects(org, agent, 1)
    prospect_id = manager_client.get("/api/prospects/").data["results"][0]["id"]
    # membership + prospect(+FK joins) + upcoming tours + tours + conversations + applications
    # + leases
    with django_assert_num_queries(7):
        resp = manager_client.get(f"/api/prospects/{prospect_id}/")
    assert resp.data["next_tour"] and len(resp.data["tours"]) == 1
