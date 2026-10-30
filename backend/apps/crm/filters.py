import django_filters as df
from django.db.models import Q

from . import models


class ProspectFilter(df.FilterSet):
    status = df.MultipleChoiceFilter(choices=models.Prospect.Status.choices)
    source = df.MultipleChoiceFilter(choices=models.Prospect.Source.choices)
    assigned_agent = df.NumberFilter(field_name="assigned_agent_id")
    unassigned = df.BooleanFilter(field_name="assigned_agent", lookup_expr="isnull")
    interested_property = df.NumberFilter(field_name="interested_property_id")
    created_after = df.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte")
    created_before = df.IsoDateTimeFilter(field_name="created_at", lookup_expr="lt")
    has_pets = df.BooleanFilter()
    q = df.CharFilter(method="search", label="Name, email or phone contains")

    class Meta:
        model = models.Prospect
        fields = ["status", "source", "has_pets"]

    def search(self, qs, name, value):
        value = value.strip()
        if not value:
            return qs
        return qs.filter(
            Q(first_name__icontains=value)
            | Q(last_name__icontains=value)
            | Q(email__icontains=value)
            | Q(phone__icontains=value)
        )


class TourFilter(df.FilterSet):
    start_after = df.IsoDateTimeFilter(field_name="start", lookup_expr="gte")
    start_before = df.IsoDateTimeFilter(field_name="start", lookup_expr="lt")
    status = df.MultipleChoiceFilter(choices=models.Tour.Status.choices)
    agent = df.NumberFilter(field_name="agent_id")
    unit = df.NumberFilter(field_name="unit_id")
    property = df.NumberFilter(field_name="unit__property_id")
    prospect = df.NumberFilter(field_name="prospect_id")

    class Meta:
        model = models.Tour
        fields = ["status"]


class ConversationFilter(df.FilterSet):
    channel = df.ChoiceFilter(choices=models.Channel.choices)
    needs_handoff = df.BooleanFilter()
    is_unread = df.BooleanFilter()
    prospect = df.NumberFilter(field_name="prospect_id")

    class Meta:
        model = models.Conversation
        fields = ["channel", "needs_handoff", "is_unread"]


class ApplicationFilter(df.FilterSet):
    status = df.MultipleChoiceFilter(choices=models.Application.Status.choices)
    prospect = df.NumberFilter(field_name="prospect_id")

    class Meta:
        model = models.Application
        fields = ["status"]


class LeaseFilter(df.FilterSet):
    status = df.MultipleChoiceFilter(choices=models.Lease.Status.choices)
    ends_before = df.DateFilter(field_name="end_date", lookup_expr="lt")

    class Meta:
        model = models.Lease
        fields = ["status"]


class HandoffFilter(df.FilterSet):
    status = df.ChoiceFilter(choices=models.HandoffTask.Status.choices)

    class Meta:
        model = models.HandoffTask
        fields = ["status"]
