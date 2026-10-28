from django.contrib import admin

from . import models


@admin.register(models.Prospect)
class ProspectAdmin(admin.ModelAdmin):
    list_display = ("__str__", "organization", "status", "source", "assigned_agent", "created_at")
    list_filter = ("status", "source", "organization")
    search_fields = ("first_name", "last_name", "email", "phone")
    raw_id_fields = ("assigned_agent", "interested_property")


@admin.register(models.Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("prospect", "channel", "last_message_at", "needs_handoff")
    raw_id_fields = ("prospect",)


@admin.register(models.Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "direction", "channel", "sent_at", "is_assistant")
    raw_id_fields = ("conversation", "sender")


@admin.register(models.Tour)
class TourAdmin(admin.ModelAdmin):
    list_display = ("prospect", "unit", "agent", "start", "status")
    list_filter = ("status",)
    raw_id_fields = ("prospect", "unit", "agent")


for m in (
    models.Application,
    models.ApplicationDocument,
    models.Lease,
    models.Renewal,
    models.HandoffTask,
):
    admin.site.register(m)
