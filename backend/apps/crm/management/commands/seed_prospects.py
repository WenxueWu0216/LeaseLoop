"""Bulk-generate synthetic prospects for load testing.

    python manage.py seed_prospects --count 100000

All data is fake (Faker names, example.com emails, 555 phone numbers). Prints an
API token for the org's manager so the load test can authenticate.
"""

import time

from django.core.management.base import BaseCommand
from django.db import connection
from rest_framework.authtoken.models import Token

from apps.crm.seeding import PERF_PASSWORD, make_context, seed_prospects


class Command(BaseCommand):
    help = "Bulk-insert synthetic prospects (with tours, applications, conversations)."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=1000)
        parser.add_argument("--batch-size", type=int, default=5000)
        parser.add_argument("--org", default="perf-org", help="Organization slug to seed into")
        parser.add_argument("--seed", type=int, default=42, help="RNG seed (reproducible data)")

    def handle(self, *args, count, batch_size, org, seed, **opts):
        t0 = time.perf_counter()
        ctx = make_context(slug=org, seed=seed)
        totals = seed_prospects(ctx, count, batch_size=batch_size, log=self.stdout.write)
        with connection.cursor() as cur:  # fresh planner statistics for EXPLAIN / load tests
            for table in ("crm_prospect", "crm_tour", "crm_application", "crm_conversation"):
                cur.execute(f"ANALYZE {table}")
        token, _ = Token.objects.get_or_create(user=ctx.manager)
        agent_token, _ = Token.objects.get_or_create(user=ctx.agents[0])
        elapsed = time.perf_counter() - t0
        self.stdout.write(self.style.SUCCESS(f"Seeded {totals} in {elapsed:.1f}s"))
        self.stdout.write(f"Manager login: {ctx.manager.email} / {PERF_PASSWORD}")
        self.stdout.write(f"Manager API token: {token.key}")
        self.stdout.write(f"Agent API token ({ctx.agents[0].email}): {agent_token.key}")
