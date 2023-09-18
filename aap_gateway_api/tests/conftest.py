import uuid

import pytest


@pytest.fixture
def unauthenticated_api_client(db):
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def admin_api_client(db, admin_user, unauthenticated_api_client):
    client = unauthenticated_api_client
    client.login(username="admin", password="password")
    yield client
    try:
        client.logout()
    except AttributeError:
        # The test might have logged the user out already (e.g. to test the logout signal)
        pass


@pytest.fixture
def randname():
    def _randname(prefix):
        return f"{prefix} {uuid.uuid4().hex[:6]}"

    return _randname


@pytest.fixture
def set_preference(db):
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
def shut_up_logging():
    """
    This fixture allows you to temporarily disable logging for a test.
    """
    import logging

    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


@pytest.fixture
def register_preference(db):
    """
    This fixture allows you to register a preference for a test and then
    unregister it (and delete its value in the database) after the test is
    complete.
    """
    from aap_gateway_api.models import Preference, gateway_preference_registry
    from aap_gateway_api.utils.preferences import get_preference_key, register

    kwargs_cache = {}

    def _register_preference(**kwargs):
        kwargs_cache.update(kwargs)
        ret = register(**kwargs)
        key = get_preference_key(kwargs["section"], kwargs["preference_name"])
        gateway_preference_registry.manager()[key]  # Register the preference in the database
        return ret

    yield _register_preference
    del gateway_preference_registry[kwargs_cache["section"]][kwargs_cache["preference_name"]]
    Preference.objects.filter(section=kwargs_cache["section"], name=kwargs_cache["preference_name"]).delete()


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
    organization = Organization.objects.create(name=random_name, environment=environment)
    yield organization
    organization.delete()
