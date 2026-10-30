import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Membership

from .factories import MembershipFactory, OrganizationFactory


@pytest.fixture
def org(db):
    return OrganizationFactory()


@pytest.fixture
def other_org(db):
    return OrganizationFactory()


@pytest.fixture
def manager(org):
    return MembershipFactory(organization=org, role=Membership.Role.PROPERTY_MANAGER).user


@pytest.fixture
def agent(org):
    return MembershipFactory(organization=org, role=Membership.Role.LEASING_AGENT).user


@pytest.fixture
def other_agent(org):
    return MembershipFactory(organization=org, role=Membership.Role.LEASING_AGENT).user


@pytest.fixture
def api_for():
    def make(user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    return make


@pytest.fixture
def manager_client(api_for, manager):
    return api_for(manager)


@pytest.fixture
def agent_client(api_for, agent):
    return api_for(agent)


@pytest.fixture
def outbox():
    from apps.integrations.outbound import LogBackend

    LogBackend.sent.clear()
    yield LogBackend.sent
    LogBackend.sent.clear()
