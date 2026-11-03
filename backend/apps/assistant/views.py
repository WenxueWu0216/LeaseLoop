from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.crm.models import Channel, Conversation, Message, Prospect
from apps.properties.models import Property

from .models import ChatSession
from .service import Assistant
from .tools import AssistantContext

HISTORY = 6


class ChatRequest(serializers.Serializer):
    property = serializers.IntegerField()
    message = serializers.CharField(max_length=1000)
    session = serializers.UUIDField(required=False)
    name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)


class ChatResponse(serializers.Serializer):
    session = serializers.UUIDField()
    reply = serializers.CharField()
    handoff = serializers.BooleanField()
    tour_id = serializers.IntegerField(allow_null=True)


def history_for(conversation: Conversation, before: Message) -> list[Message]:
    qs = conversation.messages.filter(sent_at__lte=before.sent_at).exclude(pk=before.pk)
    return list(reversed(qs.order_by("-sent_at")[:HISTORY]))


class ChatView(APIView):
    """Public renter chat widget. Anonymous, throttled, identified by a session token."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "assistant_chat"

    @extend_schema(request=ChatRequest, responses=ChatResponse)
    def post(self, request):
        data = ChatRequest(data=request.data)
        data.is_valid(raise_exception=True)
        prop = get_object_or_404(Property, pk=data.validated_data["property"])
        session = self._session(prop, data.validated_data)
        conversation = session.conversation
        inbound = Message.objects.create(
            organization_id=prop.organization_id,
            conversation=conversation,
            direction=Message.Direction.INBOUND,
            channel=Channel.CHAT,
            body=data.validated_data["message"],
            sent_at=timezone.now(),
        )
        ctx = AssistantContext(
            prop=prop,
            now=timezone.now(),
            mode="chat",
            prospect=conversation.prospect,
            conversation=conversation,
        )
        reply = Assistant().respond(ctx, inbound.body, history_for(conversation, inbound))
        return Response(
            ChatResponse(
                {
                    "session": session.token,
                    "reply": reply.text,
                    "handoff": reply.handed_off,
                    "tour_id": reply.booked_tour_id,
                }
            ).data
        )

    @staticmethod
    def _session(prop: Property, data: dict) -> ChatSession:
        token = data.get("session")
        if token:
            existing = (
                ChatSession.objects.select_related("conversation__prospect")
                .filter(token=token, property=prop)
                .first()
            )
            if existing:
                return existing
        name = (data.get("name") or "").strip()
        first, _, last = name.partition(" ")
        with transaction.atomic():
            prospect = Prospect.objects.create(
                organization_id=prop.organization_id,
                first_name=first,
                last_name=last,
                email=(data.get("email") or "").lower(),
                phone=data.get("phone") or "",
                source=Prospect.Source.CHAT,
                interested_property=prop,
            )
            conversation = Conversation.objects.create(
                organization_id=prop.organization_id,
                prospect=prospect,
                channel=Channel.CHAT,
                subject="Website chat",
            )
            return ChatSession.objects.create(property=prop, conversation=conversation)


class SuggestReplySerializer(serializers.Serializer):
    suggestion = serializers.CharField()
    handoff_reason = serializers.CharField(allow_null=True)
    tools_called = serializers.ListField(child=serializers.CharField())


def suggest_reply(conversation: Conversation) -> dict:
    """Draft an answer to the latest inbound message for the agent to review."""
    last = (
        conversation.messages.filter(direction=Message.Direction.INBOUND)
        .order_by("-sent_at")
        .first()
    )
    prop = (
        conversation.prospect.interested_property
        or Property.objects.filter(organization_id=conversation.organization_id)
        .order_by("pk")
        .first()
    )
    if last is None or prop is None:
        return {"suggestion": "", "handoff_reason": None, "tools_called": []}
    ctx = AssistantContext(
        prop=prop,
        now=timezone.now(),
        mode="draft",
        prospect=conversation.prospect,
        conversation=conversation,
    )
    reply = Assistant().respond(ctx, last.body, history_for(conversation, last))
    return {
        "suggestion": reply.text,
        "handoff_reason": reply.handoff_reason,
        "tools_called": [c["name"] for c in reply.tools_called],
    }
