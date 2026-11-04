from django.core.management.base import BaseCommand
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from rest_framework.test import force_authenticate

from apps.accounts.models import User
from apps.crm.views import ConversationViewSet, ProspectViewSet

ENDPOINTS = {
    "prospects": (ProspectViewSet, "/api/prospects/", "crm_prospect"),
    "conversations": (ConversationViewSet, "/api/conversations/", "crm_conversation"),
}


class Command(BaseCommand):
    help = "EXPLAIN ANALYZE the exact SQL a list endpoint runs."

    def add_arguments(self, parser):
        parser.add_argument("--endpoint", choices=sorted(ENDPOINTS), default="prospects")
        parser.add_argument("--email", default="manager@org1.demo")
        parser.add_argument("--query", default="", help="e.g. 'status=CONTACTED' or 'page=500'")

    def handle(self, *args, **opts):
        viewset, path, table = ENDPOINTS[opts["endpoint"]]
        user = User.objects.get(email=opts["email"])
        raw = RequestFactory().get(f"{path}?{opts['query']}", HTTP_HOST="localhost")
        force_authenticate(raw, user=user)
        # Render the real response while capturing every statement it issues.
        with CaptureQueriesContext(connection) as ctx:
            viewset.as_view({"get": "list"})(raw).render()
        for i, q in enumerate(ctx.captured_queries, 1):
            sql = q["sql"]
            if not sql.lstrip().upper().startswith("SELECT") or table not in sql:
                continue
            with connection.cursor() as cur:
                cur.execute(f"EXPLAIN (ANALYZE, BUFFERS) {sql}")
                plan = "\n".join(row[0] for row in cur.fetchall())
            self.stdout.write(f"--- query {i}: {sql[:160]}...\n{plan}\n")
