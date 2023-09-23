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
def user(db, django_user_model):
    user = django_user_model.objects.create_user(username="user", password="password")
    yield user
    user.delete()


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


@pytest.fixture
def rsa_keypair():
    from aap_gateway_api.utils.jwt_token import generate_jwt_keypair

    return generate_jwt_keypair()


@pytest.fixture
def ldap_configuration():
    return {
        "SERVER_URI": ["ldap://ldap06.example.com:389"],
        "BIND_DN": "cn=ldapadmin,dc=example,dc=org",
        "BIND_PASSWORD": "securepassword",
        "START_TLS": False,
        "CONNECTION_OPTIONS": {"OPT_REFERRALS": 0, "OPT_NETWORK_TIMEOUT": 30},
        "USER_SEARCH": ["ou=users,dc=example,dc=org", "SCOPE_SUBTREE", "(cn=%(user)s)"],
        "USER_DN_TEMPLATE": "cn=%(user)s,ou=users,dc=example,dc=org",
        "USER_ATTR_MAP": {"email": "mail", "last_name": "sn", "first_name": "givenName"},
        "GROUP_SEARCH": ["ou=groups,dc=example,dc=org", "SCOPE_SUBTREE", "(objectClass=groupOfNames)"],
        "GROUP_TYPE": "MemberDNGroupType",
        "GROUP_TYPE_PARAMS": {"name_attr": "cn", "member_attr": "member"},
    }


@pytest.fixture
def ldap_authenticator(ldap_configuration):
    from aap_gateway_api.models import Authenticator

    authenticator = Authenticator.objects.create(
        name="Test LDAP Authenticator", enabled=True, create_objects=True, users_unique=False, remove_users=True, type="l", configuration=ldap_configuration
    )
    yield authenticator
    authenticator.delete()
