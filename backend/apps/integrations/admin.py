from django.contrib import admin

from .models import LeadSourceSync, WebhookEvent


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("provider", "event_id", "status", "attempts", "organization", "created_at")
    list_filter = ("provider", "status")
    search_fields = ("event_id",)


@admin.register(LeadSourceSync)
class LeadSourceSyncAdmin(admin.ModelAdmin):
    list_display = ("organization", "source", "cursor", "last_synced_at", "last_error")
