from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounts.views import LoginView, MembershipViewSet, me
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

urlpatterns = [
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/me/", me, name="me"),
    path("webhooks/", include("apps.integrations.urls")),
    *router.urls,
]
