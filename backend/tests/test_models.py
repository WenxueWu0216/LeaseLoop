from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import Membership, User
from apps.crm.models import Message, Prospect

from .factories import (
    ConversationFactory,
    MembershipFactory,
    OrganizationFactory,
    ProspectFactory,
    TourFactory,
    UnitFactory,
)

pytestmark = pytest.mark.django_db


def test_user_logs_in_by_email():
    user = User.objects.create_user("Agent@Example.com", "secret-pass-1")
    assert user.email == "Agent@example.com"
    assert user.check_password("secret-pass-1")
    assert not hasattr(user, "username") or user.username is None


def test_organization_slug_is_generated():
    assert OrganizationFactory(name="Sunset Living", slug="").slug == "sunset-living"


def test_membership_is_unique_per_org_and_role_helper():
    m = MembershipFactory(role=Membership.Role.PROPERTY_MANAGER)
    assert m.is_manager
    with pytest.raises(IntegrityError), transaction.atomic():
        MembershipFactory(user=m.user, organization=m.organization)
    # Same user can join a different org.
    assert not MembershipFactory(user=m.user).is_manager


def test_unit_number_unique_within_property():
    unit = UnitFactory(number="101")
    with pytest.raises(IntegrityError), transaction.atomic():
        UnitFactory(property=unit.property, number="101")
    UnitFactory(number="101")  # other property is fine


def test_prospect_external_id_unique_per_org_and_source():
    p = ProspectFactory(source=Prospect.Source.ZILLOW, external_id="z-1")
    with pytest.raises(IntegrityError), transaction.atomic():
        ProspectFactory(
            organization=p.organization, source=Prospect.Source.ZILLOW, external_id="z-1"
        )
    # Blank external ids never collide; other orgs/sources are independent.
    ProspectFactory(organization=p.organization, external_id="")
    ProspectFactory(organization=p.organization, external_id="")
    ProspectFactory(source=Prospect.Source.ZILLOW, external_id="z-1")
    ProspectFactory(
        organization=p.organization, source=Prospect.Source.APARTMENTS_COM, external_id="z-1"
    )


def test_message_provider_id_unique():
    conv = ConversationFactory()
    kwargs = dict(
        organization=conv.organization,
        conversation=conv,
        direction="IN",
        channel="EMAIL",
        body="hi",
        sent_at=timezone.now(),
        provider="sendgrid",
    )
    Message.objects.create(provider_message_id="abc", **kwargs)
    Message.objects.create(provider_message_id="", **kwargs)
    Message.objects.create(provider_message_id="", **kwargs)
    with pytest.raises(IntegrityError), transaction.atomic():
        Message.objects.create(provider_message_id="abc", **kwargs)


def test_tour_must_end_after_start():
    tour = TourFactory()
    assert tour.unit.organization == tour.organization
    tour.end = tour.start - timedelta(minutes=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        tour.save()


def test_prospect_full_name_falls_back_to_contact():
    assert ProspectFactory(first_name="", last_name="", email="a@b.co").full_name == "a@b.co"
