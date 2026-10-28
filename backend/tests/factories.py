from datetime import timedelta
from decimal import Decimal

import factory
from django.utils import timezone

from apps.accounts.models import Membership, Organization, User
from apps.crm import models as crm
from apps.properties.models import Property, PropertyPolicy, Unit


class OrganizationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Organization

    name = factory.Sequence(lambda n: f"Org {n}")
    slug = factory.Sequence(lambda n: f"org-{n}")


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    password = factory.django.Password("pass1234!")


class MembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Membership

    user = factory.SubFactory(UserFactory)
    organization = factory.SubFactory(OrganizationFactory)
    role = Membership.Role.LEASING_AGENT


class PropertyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Property

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f"The Residences {n}")
    address = factory.Faker("street_address")
    city = "Austin"
    state = "TX"
    zip_code = "78701"


class UnitFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Unit

    property = factory.SubFactory(PropertyFactory)
    organization = factory.SelfAttribute("property.organization")
    number = factory.Sequence(lambda n: f"{100 + n}")
    beds = 1
    baths = Decimal("1.0")
    rent = Decimal("1500.00")
    available_from = factory.LazyFunction(lambda: timezone.now().date())


class PropertyPolicyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PropertyPolicy

    organization = factory.SubFactory(OrganizationFactory)
    topic = PropertyPolicy.Topic.PETS
    title = "Pet policy"
    body = "Cats and dogs under 50 lbs welcome. $300 pet deposit, $35/month pet rent."


class ProspectFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = crm.Prospect

    organization = factory.SubFactory(OrganizationFactory)
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    email = factory.Sequence(lambda n: f"prospect{n}@example.com")


class ConversationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = crm.Conversation

    prospect = factory.SubFactory(ProspectFactory)
    organization = factory.SelfAttribute("prospect.organization")
    channel = crm.Channel.EMAIL


class TourFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = crm.Tour

    prospect = factory.SubFactory(ProspectFactory)
    organization = factory.SelfAttribute("prospect.organization")
    unit = factory.SubFactory(
        UnitFactory, property__organization=factory.SelfAttribute("...organization")
    )
    start = factory.LazyFunction(lambda: timezone.now() + timedelta(days=1))
    end = factory.LazyAttribute(lambda o: o.start + timedelta(minutes=30))
