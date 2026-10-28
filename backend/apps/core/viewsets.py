from django.db.models import QuerySet
from rest_framework import viewsets

from apps.core.permissions import IsOrgMember
from apps.core.tenancy import resolve_membership


class OrgScopedViewSetMixin:
    """Restricts every queryset to the caller's organization.

    Objects outside the org are simply absent from the queryset, so detail
    routes return 404 rather than 403 and never leak existence.
    Subclasses add role-based narrowing in ``scope_for_agent``.
    """

    permission_classes = [IsOrgMember]

    @property
    def membership(self):
        return resolve_membership(self.request)

    @property
    def organization(self):
        return self.membership.organization

    def get_queryset(self) -> QuerySet:
        qs = super().get_queryset().filter(organization=self.organization)
        if not self.membership.is_manager:
            qs = self.scope_for_agent(qs)
        return qs

    def scope_for_agent(self, qs: QuerySet) -> QuerySet:
        return qs

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        if self.request and self.request.user.is_authenticated:
            ctx["organization"] = self.organization
            ctx["membership"] = self.membership
        return ctx

    def perform_create(self, serializer):
        serializer.save(organization=self.organization)


class OrgScopedModelViewSet(OrgScopedViewSetMixin, viewsets.ModelViewSet):
    pass
