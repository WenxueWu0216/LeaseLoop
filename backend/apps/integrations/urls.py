from django.urls import path

from .views import SendGridInboundView, TwilioInboundView

urlpatterns = [
    path("sendgrid/inbound/", SendGridInboundView.as_view(), name="sendgrid-inbound"),
    path("twilio/sms/", TwilioInboundView.as_view(), name="twilio-sms"),
]
