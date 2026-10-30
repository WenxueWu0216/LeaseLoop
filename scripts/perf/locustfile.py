"""Load test for the main list/detail endpoints against seed_demo data.

    python manage.py demo_tokens > /tmp/tokens.json
    LOCUST_TOKENS=/tmp/tokens.json LOCUST_RAW_CSV=/tmp/raw.csv \
        locust -f scripts/perf/locustfile.py --host http://localhost:8000 \
        --headless -u 50 -r 25 -t 3m --reset-stats

Each simulated user acts as a random manager or agent from the demo orgs. With
LOCUST_TOKENS set, users reuse existing API tokens instead of logging in, so the
password hashing of 50+ simultaneous logins doesn't pollute steady-state numbers.
LOCUST_RAW_CSV records every request so percentiles can be recomputed exactly.
"""

import json
import os
import random
import time
from pathlib import Path

from locust import HttpUser, between, events, task

TOKENS = (
    json.loads(Path(os.environ["LOCUST_TOKENS"]).read_text())
    if os.environ.get("LOCUST_TOKENS")
    else None
)
RAW_CSV = os.environ.get("LOCUST_RAW_CSV")
# Kept open for the whole run and closed on quit; the listener writes one line per request.
_raw = open(RAW_CSV, "w") if RAW_CSV else None  # noqa: SIM115


@events.quitting.add_listener
def close_raw(**kwargs):
    if _raw:
        _raw.close()


@events.request.add_listener
def record(request_type, name, response_time, exception, **kwargs):
    if _raw:
        _raw.write(f"{time.time():.3f},{name},{response_time:.2f},{int(exception is not None)}\n")


PASSWORD = "demo1234!"
SURNAMES = [
    "smith",
    "johnson",
    "williams",
    "brown",
    "jones",
    "garcia",
    "miller",
    "davis",
    "martinez",
    "lee",
    "walker",
    "hall",
    "young",
    "allen",
    "king",
]


class LeasingAgent(HttpUser):
    wait_time = between(0.5, 2)

    def on_start(self):
        org = random.randint(1, 4)
        who = "manager" if random.random() < 0.25 else f"agent{random.randint(1, 8)}"
        email = f"{who}@org{org}.demo"
        if TOKENS:
            token = TOKENS[email]
        else:
            resp = self.client.post(
                "/api/auth/login/",
                json={"username": email, "password": PASSWORD},
                name="setup: login",
            )
            token = resp.json()["token"]
        self.client.headers["Authorization"] = f"Token {token}"
        page = self.client.get("/api/prospects/?page_size=100", name="setup: prospect ids")
        self.prospect_ids = [r["id"] for r in page.json()["results"]] or [0]

    @task(10)
    def prospect_list(self):
        self.client.get("/api/prospects/", name="/api/prospects/")

    @task(5)
    def prospect_list_by_status(self):
        status = random.choice(["NEW", "CONTACTED", "TOURED", "APPLIED"])
        self.client.get(f"/api/prospects/?status={status}", name="/api/prospects/?status=")

    @task(2)
    def prospect_list_deep_page(self):
        self.client.get(
            f"/api/prospects/?page={random.randint(2, 200)}",
            name="/api/prospects/?page=N",
        )

    @task(3)
    def prospect_search(self):
        self.client.get(f"/api/prospects/?q={random.choice(SURNAMES)}", name="/api/prospects/?q=")

    @task(8)
    def prospect_detail(self):
        self.client.get(
            f"/api/prospects/{random.choice(self.prospect_ids)}/",
            name="/api/prospects/{id}/",
        )

    @task(3)
    def tours(self):
        self.client.get("/api/tours/?status=SCHEDULED", name="/api/tours/")

    @task(2)
    def units(self):
        self.client.get("/api/units/?status=AVAILABLE", name="/api/units/")

    @task(4)
    def inbox(self):
        self.client.get("/api/conversations/", name="/api/conversations/")
