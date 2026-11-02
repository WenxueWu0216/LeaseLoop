from rest_framework import mixins, viewsets

from apps.core.viewsets import OrgScopedModelViewSet, OrgScopedViewSetMixin

from . import models, serializers
from .scoping import prospect_visibility, tour_visibility


class ProspectViewSet(OrgScopedModelViewSet):
    queryset = models.Prospect.objects.order_by("-created_at", "-id")
    serializer_class = serializers.ProspectSerializer

    def get_queryset(self):
        # Agent, property, counts and next tour in the same query: no N+1.
        return super().get_queryset().with_list_data()

    def list(self, request, *args, **kwargs):
        """Paginate ids first, then annotate only the rows on the page.

        With OFFSET, Postgres evaluates SELECT-list subqueries for every
        skipped row: page 2000 ran the count subqueries 50,000 times.
        ``values_list("pk")`` drops the unused annotations, so the OFFSET
        scan is a plain index scan and the subqueries run 25 times.
        """
        queryset = self.filter_queryset(self.get_queryset())
        page_ids = self.paginate_queryset(queryset.values_list("pk", flat=True))
        if page_ids is None:
            return super().list(request, *args, **kwargs)
        rows = {p.pk: p for p in queryset.filter(pk__in=list(page_ids))}
        serializer = self.get_serializer([rows[pk] for pk in page_ids], many=True)
        return self.get_paginated_response(serializer.data)

    def scope_for_agent(self, qs):
        return qs.filter(prospect_visibility(self.request.user))


class TourViewSet(OrgScopedModelViewSet):
    queryset = models.Tour.objects.order_by("start")
    serializer_class = serializers.TourSerializer

    def scope_for_agent(self, qs):
        return qs.filter(tour_visibility(self.request.user))


class ProspectChildMixin:
    """Children of a prospect inherit the prospect's agent visibility."""

    def scope_for_agent(self, qs):
        return qs.filter(prospect_visibility(self.request.user, prefix="prospect__"))


class ConversationViewSet(
    ProspectChildMixin,
    OrgScopedViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = models.Conversation.objects.order_by("-last_message_at")
    serializer_class = serializers.ConversationSerializer


class ApplicationViewSet(ProspectChildMixin, OrgScopedModelViewSet):
    queryset = models.Application.objects.order_by("-created_at")
    serializer_class = serializers.ApplicationSerializer


class LeaseViewSet(ProspectChildMixin, OrgScopedModelViewSet):
    queryset = models.Lease.objects.order_by("-created_at")
    serializer_class = serializers.LeaseSerializer


class RenewalViewSet(OrgScopedModelViewSet):
    queryset = models.Renewal.objects.order_by("-created_at")
    serializer_class = serializers.RenewalSerializer

    def scope_for_agent(self, qs):
        return qs.filter(prospect_visibility(self.request.user, prefix="lease__prospect__"))


class HandoffTaskViewSet(
    ProspectChildMixin,
    OrgScopedViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = models.HandoffTask.objects.order_by("-created_at")
    serializer_class = serializers.HandoffTaskSerializer
