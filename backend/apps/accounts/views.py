from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.permissions import IsManager
from apps.core.viewsets import OrgScopedViewSetMixin

from .models import Membership
from .serializers import MembershipSerializer, MeSerializer


class LoginView(ObtainAuthToken):
    """POST {username: email, password} → {token}."""


@extend_schema(responses=MeSerializer)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    return Response(MeSerializer(request.user).data)


class MembershipViewSet(
    OrgScopedViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Team management: managers only."""

    queryset = Membership.objects.select_related("user").order_by("id")
    serializer_class = MembershipSerializer
    permission_classes = [IsManager]
