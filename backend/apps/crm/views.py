from datetime import timedelta

from django.db import transaction
from django.db.models import Count, OuterRef, Prefetch, Q, Subquery
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core.permissions import IsManager
from apps.core.viewsets import OrgScopedModelViewSet, OrgScopedViewSetMixin
from apps.properties.models import Unit

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
                "leases",
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
    queryset = models.Tour.objects.select_related("prospect", "unit__property", "agent").order_by(
        "start"
    )
    serializer_class = serializers.TourCalendarSerializer
    filterset_class = filters.TourFilter
    ordering_fields = ["start"]

    def scope_for_agent(self, qs):
        return qs.filter(tour_visibility(self.request.user))

    def perform_create(self, serializer):
        tour = serializer.save(organization=self.organization)
        # Same pipeline step as an assistant-booked tour.
        models.Prospect.objects.filter(
            pk=tour.prospect_id,
            status__in=[models.Prospect.Status.NEW, models.Prospect.Status.CONTACTED],
        ).update(status=models.Prospect.Status.TOUR_SCHEDULED)


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
    queryset = models.Conversation.objects.order_by("-last_message_at", "-id")
    serializer_class = serializers.ConversationSerializer
    filterset_class = filters.ConversationFilter

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == "list":
            last = models.Message.objects.filter(conversation=OuterRef("pk")).order_by("-sent_at")
            qs = qs.select_related("prospect").annotate(
                last_body=Subquery(last.values("body")[:1]),
                last_direction=Subquery(last.values("direction")[:1]),
                last_is_assistant=Subquery(last.values("is_assistant")[:1]),
                open_handoffs=Count(
                    "handoffs", filter=Q(handoffs__status=models.HandoffTask.Status.OPEN)
                ),
            )
        return qs

    def get_serializer_class(self):
        if self.action == "list":
            return serializers.InboxConversationSerializer
        return serializers.ConversationSerializer

    @extend_schema(
        request=serializers.ReplySerializer, responses=serializers.MessageSerializer(many=True)
    )
    @action(detail=True, methods=["get", "post"])
    def messages(self, request, pk=None):
        """GET the thread (oldest first); POST an agent reply on the conversation's channel."""
        conv = self.get_object()
        if request.method == "POST":
            data = serializers.ReplySerializer(data=request.data)
            data.is_valid(raise_exception=True)
            send_agent_reply(conv, request.user, data.validated_data["body"])
        thread = conv.messages.order_by("sent_at", "id")[:500]
        return Response(serializers.MessageSerializer(thread, many=True).data)

    @extend_schema(request=None, responses={200: dict})
    @action(detail=True, methods=["post"], url_path="suggest-reply")
    def suggest_reply(self, request, pk=None):
        from apps.assistant.views import suggest_reply

        return Response(suggest_reply(self.get_object()))


def send_agent_reply(conv, user, body: str) -> models.Message:
    from apps.integrations.outbound import OutboundRequest, get_backend

    now = timezone.now()
    prospect = conv.prospect
    to = prospect.phone if conv.channel == models.Channel.SMS else prospect.email
    message = models.Message.objects.create(
        organization_id=conv.organization_id,
        conversation=conv,
        direction=models.Message.Direction.OUTBOUND,
        channel=conv.channel,
        body=body,
        sender=user,
        sent_at=now,
    )
    if conv.channel != models.Channel.CHAT and to:
        get_backend().send(
            OutboundRequest(
                to=to, channel=conv.channel, body=body, idempotency_key=f"message:{message.pk}"
            )
        )
    models.Conversation.objects.filter(pk=conv.pk).update(last_message_at=now, is_unread=False)
    updates = {"last_contacted_at": now}
    if prospect.status == models.Prospect.Status.NEW:
        updates["status"] = models.Prospect.Status.CONTACTED
    models.Prospect.objects.filter(pk=prospect.pk).update(**updates)
    return message


class ApplicationViewSet(ProspectChildMixin, OrgScopedModelViewSet):
    queryset = models.Application.objects.order_by("-created_at")
    serializer_class = serializers.ApplicationSerializer
    filterset_class = filters.ApplicationFilter

    def _transition(self, app, allowed_from, to, prospect_status=None, **fields):
        if app.status not in allowed_from:
            raise ValidationError(
                {"status": f"Can't move a {app.status.lower()} application " f"to {to.lower()}."}
            )
        app.status = to
        for k, v in fields.items():
            setattr(app, k, v)
        app.save()
        if prospect_status:
            models.Prospect.objects.filter(pk=app.prospect_id).update(status=prospect_status)
        return Response(
            serializers.ApplicationSerializer(app, context=self.get_serializer_context()).data
        )

    @extend_schema(request=None, responses=serializers.ApplicationSerializer)
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        return self._transition(
            self.get_object(),
            {models.Application.Status.DRAFT},
            models.Application.Status.SUBMITTED,
            models.Prospect.Status.APPLIED,
            submitted_at=timezone.now(),
        )

    @extend_schema(request=None, responses=serializers.ApplicationSerializer)
    @action(detail=True, methods=["post"], permission_classes=[IsManager])
    def approve(self, request, pk=None):
        app = self.get_object()
        return self._transition(
            app,
            {models.Application.Status.SUBMITTED, models.Application.Status.SCREENING},
            models.Application.Status.APPROVED,
            models.Prospect.Status.APPROVED,
            decided_at=timezone.now(),
        )

    @extend_schema(request=serializers.CreateLeaseSerializer, responses=serializers.LeaseSerializer)
    @action(detail=True, methods=["post"], url_path="lease")
    def create_lease(self, request, pk=None):
        app = self.get_object()
        if app.status != models.Application.Status.APPROVED:
            raise ValidationError({"status": "Only approved applications can become leases."})
        if models.Lease.objects.filter(application=app).exists():
            raise ValidationError({"application": "This application already has a lease."})
        data = serializers.CreateLeaseSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        start = data.validated_data["start_date"]
        months = data.validated_data["term_months"]
        lease = models.Lease.objects.create(
            organization_id=app.organization_id,
            application=app,
            prospect=app.prospect,
            unit=app.unit,
            start_date=start,
            term_months=months,
            end_date=start + timedelta(days=round(months * 30.44)),
            monthly_rent=app.unit.rent,
        )
        return Response(
            serializers.LeaseSerializer(lease, context=self.get_serializer_context()).data,
            status=201,
        )


class LeaseViewSet(ProspectChildMixin, OrgScopedModelViewSet):
    queryset = models.Lease.objects.order_by("-created_at")
    serializer_class = serializers.LeaseSerializer
    filterset_class = filters.LeaseFilter

    @extend_schema(request=None, responses=serializers.LeaseSerializer)
    @action(detail=True, methods=["post"])
    def sign(self, request, pk=None):
        lease = self.get_object()
        if lease.status not in (models.Lease.Status.DRAFT, models.Lease.Status.SENT):
            raise ValidationError({"status": "This lease is already signed."})
        with transaction.atomic():
            lease.status = models.Lease.Status.SIGNED
            lease.signed_at = timezone.now()
            lease.save(update_fields=["status", "signed_at", "updated_at"])
            models.Prospect.objects.filter(pk=lease.prospect_id).update(
                status=models.Prospect.Status.LEASED
            )
            Unit.objects.filter(pk=lease.unit_id).update(
                status=Unit.Status.OCCUPIED, available_from=None
            )
        return Response(
            serializers.LeaseSerializer(lease, context=self.get_serializer_context()).data
        )


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
    queryset = models.HandoffTask.objects.select_related("prospect").order_by("-created_at")
    serializer_class = serializers.HandoffTaskSerializer
    filterset_class = filters.HandoffFilter
