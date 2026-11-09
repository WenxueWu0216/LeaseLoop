import json

from django.core.management.base import BaseCommand
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import User


class Command(BaseCommand):
    help = "Print short-lived (15 min) JWT access tokens for seed_demo users, for load tests."

    def handle(self, *args, **opts):
        users = User.objects.filter(email__endswith=".demo")
        self.stdout.write(json.dumps({u.email: str(AccessToken.for_user(u)) for u in users}))
