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
        return attrs


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
