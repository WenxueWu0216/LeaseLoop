"""Agent visibility rules, shared by viewsets and serializer FK fields."""

from django.db.models import Q, QuerySet


def prospect_visibility(user, prefix: str = "") -> Q:
    """Agents see prospects assigned to them or still unassigned."""
    field = f"{prefix}assigned_agent"
    return Q(**{field: user}) | Q(**{f"{field}__isnull": True})


def tour_visibility(user) -> Q:
    return Q(agent=user) | Q(agent__isnull=True)


def visible_prospects(qs: QuerySet, membership) -> QuerySet:
    if membership.is_manager:
        return qs
    return qs.filter(prospect_visibility(membership.user))
