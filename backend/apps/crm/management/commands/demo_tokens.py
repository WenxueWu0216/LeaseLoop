import json

from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token


class Command(BaseCommand):
    help = "Print API tokens of seed_demo users as JSON (for load tests)."

    def handle(self, *args, **opts):
        tokens = Token.objects.filter(user__email__endswith=".demo").select_related("user")
        self.stdout.write(json.dumps({t.user.email: t.key for t in tokens}))
