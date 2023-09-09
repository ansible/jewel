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
def register_preference(db):
    """
    This fixture allows you to register a preference for a test and then
    unregister it (and delete its value in the database) after the test is
    complete.
    """
    from aap_gateway_api.models import Preference, gateway_preference_registry
    from aap_gateway_api.utils.preferences import register, get_preference_key

    kwargs = {}

    def _register_preference(
        section="general",
        preference_name=None,
        default=None,
        required=False,
        encrypted=False,
        preference_type=None,
        help_text=None,
    ):
        kwargs["section"] = section
        kwargs["preference_name"] = preference_name
        kwargs["default"] = default
        kwargs["required"] = required
        kwargs["encrypted"] = encrypted
        kwargs["preference_type"] = preference_type
        kwargs["help_text"] = help_text
        ret = register(
            section,
            preference_name,
            default,
            required,
            encrypted,
            preference_type,
            help_text,
        )
        key = get_preference_key(section, preference_name)
        gateway_preference_registry.manager()[
            key
        ]  # Register the preference in the database
        return ret

    yield _register_preference
    del gateway_preference_registry[kwargs["section"]][kwargs["preference_name"]]
    Preference.objects.filter(
        section=kwargs["section"], name=kwargs["preference_name"]
    ).delete()


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
