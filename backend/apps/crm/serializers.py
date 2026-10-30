from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.models import User
from apps.core.serializers import OrgMemberUserField, OrgScopedPrimaryKeyRelatedField
from apps.properties.models import Property, Unit

from . import models
from .scoping import visible_prospects


class VisibleProspectField(OrgScopedPrimaryKeyRelatedField):
    """Prospect FK limited to the org and, for agents, to prospects they can see."""

    def get_queryset(self):
        qs = super().get_queryset()
        membership = self.context.get("membership")
        return visible_prospects(qs, membership) if membership else qs.none()


class AgentAssignmentMixin:
    """Agents may only assign work to themselves (or leave it unassigned)."""

    assignment_field = "assigned_agent"

    def validate(self, attrs):
        attrs = super().validate(attrs)
        membership = self.context["membership"]
        agent = attrs.get(self.assignment_field)
        if not membership.is_manager and agent is not None and agent != membership.user:
            raise serializers.ValidationError(
                {self.assignment_field: "Agents can only assign to themselves."}
            )
        return attrs


class ProspectSerializer(AgentAssignmentMixin, serializers.ModelSerializer):
    assigned_agent = OrgMemberUserField(
        queryset=User.objects.all(), required=False, allow_null=True
    )
    interested_property = OrgScopedPrimaryKeyRelatedField(
        queryset=Property.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = models.Prospect
        exclude = ["organization"]
        read_only_fields = ["created_at", "updated_at", "last_contacted_at", "last_followup_at"]


class TourSerializer(AgentAssignmentMixin, serializers.ModelSerializer):
    assignment_field = "agent"
    prospect = VisibleProspectField(queryset=models.Prospect.objects.all())
    unit = OrgScopedPrimaryKeyRelatedField(queryset=Unit.objects.all())
    agent = OrgMemberUserField(queryset=User.objects.all(), required=False, allow_null=True)

    class Meta:
        model = models.Tour
        exclude = ["organization"]
        read_only_fields = [
            "reminder_24h_sent_at",
            "reminder_1h_sent_at",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        start = attrs.get("start", getattr(self.instance, "start", None))
        end = attrs.get("end", getattr(self.instance, "end", None))
        if start and end and end <= start:
            raise serializers.ValidationError({"end": "Tour must end after it starts."})
        unit = attrs.get("unit", getattr(self.instance, "unit", None))
        status = attrs.get("status", getattr(self.instance, "status", models.Tour.Status.SCHEDULED))
        if unit and start and end and status == models.Tour.Status.SCHEDULED:
            clash = models.Tour.objects.filter(
                unit=unit, status=models.Tour.Status.SCHEDULED, start__lt=end, end__gt=start
            )
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError(
                    {"start": "Another tour of this unit overlaps that time."}
                )
        return attrs


class TourCalendarSerializer(TourSerializer):
    """Tour row for the calendar: ids for writes plus display names (joined, no N+1)."""

    prospect_name = serializers.CharField(source="prospect.full_name", read_only=True)
    unit_number = serializers.CharField(source="unit.number", read_only=True)
    property_id = serializers.IntegerField(source="unit.property_id", read_only=True)
    property_name = serializers.CharField(source="unit.property.name", read_only=True)
    timezone = serializers.CharField(source="unit.property.timezone", read_only=True)
    agent_name = serializers.SerializerMethodField()

    class Meta(TourSerializer.Meta):
        pass

    def get_agent_name(self, tour) -> str | None:
        return tour.agent.get_full_name() if tour.agent else None


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Message
        fields = [
            "id",
            "conversation",
            "direction",
            "channel",
            "body",
            "sender",
            "is_assistant",
            "sent_at",
        ]
        read_only_fields = fields


class ProspectMiniSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="full_name", read_only=True)

    class Meta:
        model = models.Prospect
        fields = ["id", "name", "email", "phone", "status", "assigned_agent"]


class InboxConversationSerializer(serializers.ModelSerializer):
    """Inbox row. Last message and open handoffs come from queryset annotations."""

    prospect = ProspectMiniSerializer(read_only=True)
    last_message = serializers.SerializerMethodField()
    open_handoffs = serializers.IntegerField(read_only=True)

    class Meta:
        model = models.Conversation
        fields = [
            "id",
            "channel",
            "subject",
            "last_message_at",
            "is_unread",
            "needs_handoff",
            "prospect",
            "last_message",
            "open_handoffs",
        ]

    def get_last_message(self, conv) -> dict | None:
        if conv.last_body is None:
            return None
        return {
            "body": conv.last_body[:160],
            "direction": conv.last_direction,
            "is_assistant": conv.last_is_assistant,
        }


class ReplySerializer(serializers.Serializer):
    body = serializers.CharField(max_length=2000)


class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Conversation
        exclude = ["organization"]
        read_only_fields = ["prospect", "channel", "last_message_at", "created_at", "updated_at"]


class ApplicationSerializer(serializers.ModelSerializer):
    prospect = VisibleProspectField(queryset=models.Prospect.objects.all())
    unit = OrgScopedPrimaryKeyRelatedField(queryset=Unit.objects.all())

    class Meta:
        model = models.Application
        exclude = ["organization"]
        read_only_fields = ["submitted_at", "decided_at", "created_at", "updated_at"]


class LeaseSerializer(serializers.ModelSerializer):
    prospect = VisibleProspectField(queryset=models.Prospect.objects.all())
    unit = OrgScopedPrimaryKeyRelatedField(queryset=Unit.objects.all())
    application = OrgScopedPrimaryKeyRelatedField(
        queryset=models.Application.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = models.Lease
        exclude = ["organization"]
        read_only_fields = ["signed_at", "created_at", "updated_at"]


class RenewalSerializer(serializers.ModelSerializer):
    lease = OrgScopedPrimaryKeyRelatedField(queryset=models.Lease.objects.all())

    class Meta:
        model = models.Renewal
        exclude = ["organization"]
        read_only_fields = ["responded_at", "created_at", "updated_at"]


class HandoffTaskSerializer(serializers.ModelSerializer):
    prospect_name = serializers.CharField(source="prospect.full_name", read_only=True)

    class Meta:
        model = models.HandoffTask
        exclude = ["organization"]
        read_only_fields = [
            "conversation",
            "prospect",
            "reason",
            "question",
            "created_at",
            "updated_at",
            "resolved_at",
        ]


class AgentSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", "email"]


class PropertySummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Property
        fields = ["id", "name"]


class TourSummarySerializer(serializers.ModelSerializer):
    unit_number = serializers.CharField(source="unit.number")

    class Meta:
        model = models.Tour
        fields = ["id", "start", "end", "status", "unit", "unit_number"]


class ProspectListSerializer(serializers.ModelSerializer):
    """Row shape for the prospect pipeline table."""

    assigned_agent = AgentSummarySerializer(read_only=True)
    interested_property = PropertySummarySerializer(read_only=True)
    next_tour = serializers.SerializerMethodField()

    class Meta:
        model = models.Prospect
        fields = [
            "id",
            "first_name",
            "last_name",
            "email",
            "phone",
            "source",
            "status",
            "assigned_agent",
            "interested_property",
            "desired_move_in",
            "beds_min",
            "budget_max",
            "has_pets",
            "last_contacted_at",
            "created_at",
            "next_tour",
        ]

    @extend_schema_field(TourSummarySerializer(allow_null=True))
    def get_next_tour(self, prospect):
        upcoming = getattr(prospect, "upcoming_tours", None)
        if upcoming is None:  # not prefetched (e.g. serializer used outside the viewset)
            upcoming = prospect.tours.filter(
                status=models.Tour.Status.SCHEDULED, start__gte=timezone.now()
            ).order_by("start")[:1]
        tour = next(iter(upcoming), None)
        return TourSummarySerializer(tour).data if tour else None


class ProspectDetailSerializer(ProspectListSerializer):
    tours = TourSummarySerializer(many=True, read_only=True)
    conversations = ConversationSerializer(many=True, read_only=True)
    applications = ApplicationSerializer(many=True, read_only=True)

    class Meta(ProspectListSerializer.Meta):
        fields = [
            *ProspectListSerializer.Meta.fields,
            "notes",
            "external_id",
            "updated_at",
            "tours",
            "conversations",
            "applications",
        ]
