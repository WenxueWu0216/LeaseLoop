"""Writing audit events.

Changes made through the API are recorded inside the same transaction as the change,
so an audit row exists exactly when the change committed.
"""

import ipaddress

from django.db import models, transaction
from rest_framework.throttling import BaseThrottle

from apps.accounts.models import User

from .models import AuditEvent

# Bookkeeping fields that change on every save and say nothing about intent.
IGNORED_FIELDS = {"id", "organization_id", "created_at", "updated_at"}


def client_ip(request) -> str | None:
    """Same client IP the rate limiter uses (honours NUM_PROXIES, not raw X-Forwarded-For)."""
    ident = BaseThrottle().get_ident(request)
    try:
        return str(ipaddress.ip_address(ident))
    except ValueError:
        return None


def snapshot(instance: models.Model) -> dict:
    return {
        f.attname: f.value_from_object(instance)
        for f in instance._meta.concrete_fields
        if f.attname not in IGNORED_FIELDS
    }


def diff(before: dict, after: dict) -> dict:
    keys = before.keys() | after.keys()
    return {k: [before.get(k), after.get(k)] for k in sorted(keys) if before.get(k) != after.get(k)}


def object_type(instance: models.Model) -> str:
    return instance._meta.label_lower  # e.g. "crm.prospect"


def record_change(request, action: str, instance: models.Model, changes: dict) -> AuditEvent:
    user = request.user if request.user.is_authenticated else None
    return AuditEvent.objects.create(
        organization_id=instance.organization_id,
        actor=user,
        actor_email=user.email if user else "",
        action=action,
        object_type=object_type(instance),
        object_id=str(instance.pk),
        changes=changes,
        ip=client_ip(request),
    )


def record_login(request, *, success: bool, email: str, user: User | None = None) -> None:
    """One row per org the account belongs to, so each org's managers see its logins."""
    email = (email or "").strip()[:254]
    if user is None and email:
        user = User.objects.filter(email__iexact=email).first()
    org_ids = list(user.memberships.values_list("organization_id", flat=True)) if user else []
    common = {
        "actor": user if success else None,  # a failed attempt's actor is unknown
        "actor_email": user.email if success else email,
        "action": AuditEvent.Action.LOGIN_SUCCESS if success else AuditEvent.Action.LOGIN_FAILED,
        "object_type": "accounts.user",
        "object_id": str(user.pk) if user else "",
        "ip": client_ip(request),
    }
    AuditEvent.objects.bulk_create(
        [AuditEvent(organization_id=org_id, **common) for org_id in org_ids or [None]]
    )


class AuditedViewSetMixin:
    """Records create/update/delete made through a model viewset."""

    def perform_create(self, serializer):
        with transaction.atomic():
            super().perform_create(serializer)
            obj = serializer.instance
            record_change(self.request, AuditEvent.Action.CREATE, obj, diff({}, snapshot(obj)))

    def perform_update(self, serializer):
        before = snapshot(serializer.instance)
        with transaction.atomic():
            super().perform_update(serializer)
            changes = diff(before, snapshot(serializer.instance))
            if changes:
                record_change(self.request, AuditEvent.Action.UPDATE, serializer.instance, changes)

    def perform_destroy(self, instance):
        with transaction.atomic():
            record_change(
                self.request, AuditEvent.Action.DELETE, instance, diff(snapshot(instance), {})
            )
            super().perform_destroy(instance)
