import pytest
import uuid


@pytest.fixture
def unauthenticated_api_client(db):
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def admin_api_client(db, admin_user, unauthenticated_api_client):
    client = unauthenticated_api_client
    client.force_authenticate(user=admin_user)
    yield client
    client.force_authenticate(user=None)


@pytest.fixture
def randname():
    def _randname(prefix):
        return f"{prefix} {uuid.uuid4().hex[:6]}"

    return _randname


@pytest.fixture
def set_preference():
    """
    This fixture allows you to set preference values for a test and then
    revert all preferences to their original values after the test is
    complete.
    """
    from aap_gateway_api.models import Preference
    from aap_gateway_api.utils.preferences import update_preference_value

    def _set_preference(section, name, value):
        update_preference_value(section, name, value)

    old_prefs = Preference.objects.all()
    yield _set_preference
    for pref in old_prefs:
        update_preference_value(pref.section, pref.name, pref.value)


@pytest.fixture
def environment(randname):
    from aap_gateway_api.models import Environment

    random_name = randname("Test Environment")
    environment = Environment.objects.create(name=random_name)
    yield environment
    environment.delete()


@pytest.fixture
def organization(environment, randname):
    from aap_gateway_api.models import Organization

    random_name = randname("Test Organization")
    organization = Organization.objects.create(
        name=random_name, environment=environment
    )
    yield organization
    organization.delete()
