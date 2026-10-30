from apps.core.permissions import IsManagerOrReadOnly
from apps.core.viewsets import OrgScopedModelViewSet

from .filters import PolicyFilter, UnitFilter
from .models import Property, PropertyPolicy, Unit
from .serializers import PropertyPolicySerializer, PropertySerializer, UnitSerializer


class PropertyViewSet(OrgScopedModelViewSet):
    queryset = Property.objects.order_by("name")
    serializer_class = PropertySerializer
    permission_classes = [IsManagerOrReadOnly]


class UnitViewSet(OrgScopedModelViewSet):
    queryset = Unit.objects.order_by("property_id", "number")
    serializer_class = UnitSerializer
    filterset_class = UnitFilter
    ordering_fields = ["rent", "available_from", "beds"]
    permission_classes = [IsManagerOrReadOnly]


class PropertyPolicyViewSet(OrgScopedModelViewSet):
    queryset = PropertyPolicy.objects.order_by("topic", "id")
    serializer_class = PropertyPolicySerializer
    filterset_class = PolicyFilter
    permission_classes = [IsManagerOrReadOnly]
