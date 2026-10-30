from django.core.management.base import BaseCommand

from apps.assistant.retrieval import index_policy
from apps.properties.models import PropertyPolicy


class Command(BaseCommand):
    help = "Re-chunk and re-embed property policies for assistant retrieval."

    def add_arguments(self, parser):
        parser.add_argument("--org", type=int, help="Only this organization id")

    def handle(self, *args, **opts):
        qs = PropertyPolicy.objects.all()
        if opts["org"]:
            qs = qs.filter(organization_id=opts["org"])
        chunks = sum(index_policy(p) for p in qs.iterator())
        self.stdout.write(
            self.style.SUCCESS(f"Indexed {qs.count()} policies into {chunks} chunks.")
        )
