from rest_framework import mixins, viewsets

from apps.core.viewsets import OrgScopedModelViewSet, OrgScopedViewSetMixin

from . import models, serializers
from .scoping import prospect_visibility, tour_visibility


class ProspectViewSet(OrgScopedModelViewSet):
    queryset = models.Prospect.objects.order_by("-created_at", "-id")
    serializer_class = serializers.ProspectSerializer

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
