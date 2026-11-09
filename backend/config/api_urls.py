from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounts.auth import LoginView, LogoutView, RefreshView
from apps.accounts.views import MembershipViewSet, me
from apps.audit.views import AuditEventViewSet
from apps.crm import views as crm
from apps.properties import views as props

router = DefaultRouter()
router.register("memberships", MembershipViewSet, basename="membership")
router.register("properties", props.PropertyViewSet, basename="property")
router.register("units", props.UnitViewSet, basename="unit")
router.register("policies", props.PropertyPolicyViewSet, basename="policy")
router.register("prospects", crm.ProspectViewSet, basename="prospect")
router.register("tours", crm.TourViewSet, basename="tour")
router.register("conversations", crm.ConversationViewSet, basename="conversation")
router.register("applications", crm.ApplicationViewSet, basename="application")
router.register("leases", crm.LeaseViewSet, basename="lease")
router.register("renewals", crm.RenewalViewSet, basename="renewal")
router.register("handoffs", crm.HandoffTaskViewSet, basename="handoff")
router.register("audit-events", AuditEventViewSet, basename="audit-event")

urlpatterns = [
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/refresh/", RefreshView.as_view(), name="token-refresh"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/me/", me, name="me"),
    path("webhooks/", include("apps.integrations.urls")),
    path("assistant/", include("apps.assistant.urls")),
    *router.urls,
]
