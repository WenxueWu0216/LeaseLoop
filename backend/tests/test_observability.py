import json
import logging

import pytest

from apps.core.logging import JsonFormatter

from .factories import ProspectFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def request_log(caplog):
    # The request logger doesn't propagate to root, so hook caplog in directly.
    logger = logging.getLogger("leaseloop.request")
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger="leaseloop.request")
    yield caplog
    logger.removeHandler(caplog.handler)


def test_metrics_headers_on_every_response(manager_client, org):
    ProspectFactory(organization=org)
    resp = manager_client.get("/api/prospects/", HTTP_X_REQUEST_ID="abc123")
    assert resp["X-Request-ID"] == "abc123"
    assert int(resp["X-DB-Query-Count"]) > 0
    assert resp["Server-Timing"].startswith("db;dur=")


def test_request_id_generated_when_missing(client):
    resp = client.get("/api/prospects/")
    assert len(resp["X-Request-ID"]) == 32


def test_structured_request_log(manager_client, org, request_log):
    manager_client.get("/api/prospects/")
    record = next(r for r in request_log.records if r.name == "leaseloop.request")
    fields = record.fields
    assert fields["path"] == "/api/prospects/" and fields["status"] == 200
    assert fields["org_id"] == org.pk and fields["db_queries"] > 0
    line = json.loads(JsonFormatter().format(record))
    assert line["msg"] == "request" and line["org_id"] == org.pk


def test_slow_or_chatty_requests_log_as_warning(manager_client, org, request_log, settings):
    settings.MAX_QUERIES_PER_REQUEST = 0
    manager_client.get("/api/prospects/")
    assert [r.levelno for r in request_log.records] == [logging.WARNING]
