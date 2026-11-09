from rest_framework import mixins, viewsets

from apps.core.permissions import IsManager
from apps.core.viewsets import OrgScopedViewSetMixin

from .models import AuditEvent
from .serializers import AuditEventSerializer


class AuditEventViewSet(
    OrgScopedViewSetMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """The org's audit trail, newest first. Managers only; read-only by construction."""

    queryset = AuditEvent.objects.all()
    serializer_class = AuditEventSerializer
    permission_classes = [IsManager]
    filterset_fields = ["action", "object_type", "object_id", "actor"]
