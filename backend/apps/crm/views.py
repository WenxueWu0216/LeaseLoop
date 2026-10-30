from django.db.models import Prefetch
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.viewsets import OrgScopedModelViewSet, OrgScopedViewSetMixin

from . import filters, models, serializers
from .scoping import prospect_visibility, tour_visibility


class ProspectViewSet(OrgScopedModelViewSet):
    queryset = models.Prospect.objects.order_by("-created_at", "-id")
    serializer_class = serializers.ProspectSerializer
    filterset_class = filters.ProspectFilter
    ordering_fields = ["created_at", "last_contacted_at"]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action in ("list", "retrieve"):
            # One JOIN for the FKs and one IN-query for upcoming tours, instead of
            # three lookups per row in the serializer.
            upcoming = (
                models.Tour.objects.filter(
                    status=models.Tour.Status.SCHEDULED, start__gte=timezone.now()
                )
                .select_related("unit")
                .order_by("start")
            )
            qs = qs.select_related("assigned_agent", "interested_property").prefetch_related(
                Prefetch("tours", queryset=upcoming, to_attr="upcoming_tours")
            )
        if self.action == "retrieve":
            qs = qs.prefetch_related(
                Prefetch("tours", queryset=models.Tour.objects.select_related("unit")),
                "conversations",
                "applications",
            )
        return qs

    def get_serializer_class(self):
        if self.action == "list":
            return serializers.ProspectListSerializer
        if self.action == "retrieve":
            return serializers.ProspectDetailSerializer
        return serializers.ProspectSerializer

    def scope_for_agent(self, qs):
        return qs.filter(prospect_visibility(self.request.user))


class TourViewSet(OrgScopedModelViewSet):
    queryset = models.Tour.objects.order_by("start")
    serializer_class = serializers.TourSerializer
    filterset_class = filters.TourFilter
    ordering_fields = ["start"]

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
    filterset_class = filters.ConversationFilter

    @extend_schema(request=None, responses={200: dict})
    @action(detail=True, methods=["post"], url_path="suggest-reply")
    def suggest_reply(self, request, pk=None):
        from apps.assistant.views import suggest_reply

        return Response(suggest_reply(self.get_object()))


class ApplicationViewSet(ProspectChildMixin, OrgScopedModelViewSet):
    queryset = models.Application.objects.order_by("-created_at")
    serializer_class = serializers.ApplicationSerializer
    filterset_class = filters.ApplicationFilter


class LeaseViewSet(ProspectChildMixin, OrgScopedModelViewSet):
    queryset = models.Lease.objects.order_by("-created_at")
    serializer_class = serializers.LeaseSerializer
    filterset_class = filters.LeaseFilter


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
    filterset_class = filters.HandoffFilter
