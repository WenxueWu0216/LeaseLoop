from rest_framework import serializers

from .models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "timestamp",
            "action",
            "actor",
            "actor_email",
            "object_type",
            "object_id",
            "changes",
            "ip",
        ]
        read_only_fields = fields
