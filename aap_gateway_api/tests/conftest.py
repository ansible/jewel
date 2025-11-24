import hashlib
import multiprocessing
import os
import random
import re
import uuid
from collections import namedtuple
from unittest.mock import patch

import pytest

# If we pull in individual fixtures and then reuse them in the new fixtures they have linting errors
#  around redefinition. Instead we will just import * here and noqa this one line instead of multiple places
from ansible_base.lib.testing.fixtures import *  # noqa: F403, F401
from ansible_base.lib.testing.util import copy_fixture, delete_authenticator  # noqa: F401
from ansible_base.oauth2_provider.fixtures import *  # noqa: F403, F401
from rest_framework.test import APIClient

from aap_gateway_api.models import (
    AdditionalRoute,
    CACertificate,
    DefaultServiceType,
    MigrateServiceDataHasRan,
    Preference,
    ServiceAPIRoute,
    ServiceCluster,
    ServiceNode,
    ServiceType,
    UIPluginRoute,
)
from aap_gateway_api.tests.service_test_app.launch import launch_service
from aap_gateway_api.utils.resources_client import AllServicesClient, GWResourceAPIClient


@pytest.fixture(autouse=True)
def ensure_settings_bound_preferences():
    """Ensure all settings-bound preferences have their Django settings set."""
    from django.conf import settings

    # Set default values for all settings-bound preferences to avoid None value errors
    if not hasattr(settings, 'AAP_DEPLOYMENT_TYPE'):
        setattr(settings, 'AAP_DEPLOYMENT_TYPE', 'self-managed')
    if not hasattr(settings, 'NOTIFICATION_RSS_FEED_URL'):
        setattr(settings, 'NOTIFICATION_RSS_FEED_URL', 'https://announcements.ansiblecloud.redhat.com/feed.atom')
    if not hasattr(settings, 'RUNTIME_FEATURE_FLAGS'):
        setattr(settings, 'RUNTIME_FEATURE_FLAGS', False)
    if not hasattr(settings, 'RUNTIME_FEATURE_FLAGS_UI'):
        setattr(settings, 'RUNTIME_FEATURE_FLAGS_UI', False)


def pytest_configure():
    """
    macOS uses 'spawn' by default (unlike Linux, which uses 'fork'). This causes issues with Django's app registry in subprocesses,
    as it doesn't inherit the parent process's state.
    This function sets the multiprocessing start method to 'fork' before any tests run.
    """
    try:
        multiprocessing.set_start_method("fork", force=True)
    except RuntimeError:
        # Ignore if already set
        pass


# set_preference fixture has been REMOVED!
# All tests have been migrated to use preference_manager for better isolation and cleanup.
#
# If you need to set preferences in tests, use:
# - preference_manager.set("section", "name", value) for single preferences
# - preference_manager.set_multiple({("section", "name"): value}) for multiple preferences


@pytest.fixture
def preference_manager(db):
    """
    Advanced preference management fixture that can handle multiple preferences
    and provides both context manager and direct setting capabilities.

    Usage:
        def test_password_validation(preference_manager):
            # Set multiple preferences at once
            with preference_manager.set_multiple({
                ("local_login", "password_min_upper"): 2,
                ("local_login", "password_min_special"): 2,
                ("local_login", "password_min_length"): 8,
            }):
                # All preferences are set, test code here
                pass
            # All preferences automatically restored

        def test_single_preference(preference_manager):
            # Or use for single preference (simpler syntax)
            with preference_manager.set("local_login", "password_min_upper", 2):
                # Test code here
                pass
    """
    from contextlib import contextmanager

    from django.core.cache import cache

    from aap_gateway_api.preferences import gateway_preference_registry
    from aap_gateway_api.utils.preferences import get_preference_value, update_preference_value

    class PreferenceManager:
        @contextmanager
        def set(self, section, name, value):
            """Set a single preference with automatic cleanup."""
            with self.set_multiple({(section, name): value}):
                yield

        @contextmanager
        def set_multiple(self, preferences_dict):
            """
            Set multiple preferences with automatic cleanup.

            Args:
                preferences_dict: Dict with (section, name) tuples as keys and values as values
                                 e.g., {("local_login", "password_min_upper"): 2}
            """
            original_values = {}

            # Capture original values
            for (section, name), value in preferences_dict.items():
                try:
                    original_values[(section, name)] = get_preference_value(section, name, encrypted=False)
                except Exception:
                    original_values[(section, name)] = None

            try:
                # Set all new values
                for (section, name), value in preferences_dict.items():
                    update_preference_value(section, name, value)
                yield
            finally:
                # Restore all original values and clear cache
                for (section, name), original_value in original_values.items():
                    if original_value is not None:
                        update_preference_value(section, name, original_value)

                    cache_key = gateway_preference_registry.manager().get_cache_key(section, name)
                    cache.delete(cache_key)

    return PreferenceManager()


@pytest.fixture
def register_preference(db):
    """
    This fixture allows you to register a preference for a test and then
    unregister it (and delete its value in the database) after the test is
    complete.
    """
    from aap_gateway_api.models import Preference
    from aap_gateway_api.preferences import gateway_preference_registry
    from aap_gateway_api.utils.preferences import get_preference_key, register

    kwargs_cache = {}

    def _register_preference(**kwargs):
        from django.core.cache import cache

        kwargs_cache.update(kwargs)
        ret = register(**kwargs)
        key = get_preference_key(kwargs["section"], kwargs["preference_name"])

        # Clear any existing cache entry for this preference to prevent type conflicts
        cache_key = gateway_preference_registry.manager().get_cache_key(kwargs["section"], kwargs["preference_name"])
        cache.delete(cache_key)

        gateway_preference_registry.manager()[key]  # Register the preference in the database
        return ret

    yield _register_preference

    # Cleanup: safely remove the preference
    if kwargs_cache:
        try:
            del gateway_preference_registry[kwargs_cache["section"]][kwargs_cache["preference_name"]]
        except KeyError:
            # Already removed or never existed
            pass
        Preference.objects.filter(section=kwargs_cache["section"], name=kwargs_cache["preference_name"]).delete()


@pytest.fixture
def ensure_jwt_keys():
    """
    Function-scoped fixture to ensure JWT keys are set up for service tests.
    This prevents authentication issues in service tests and works with pytest-xdist.

    IMPORTANT: This fixture explicitly commits JWT keys to the database to ensure
    they are visible to subprocess-based service tests. Without explicit commit,
    keys may not be visible to subprocesses due to transaction isolation.
    """
    # Add debug logging for CI
    import os
    import time

    from django.db import connection, transaction

    from aap_gateway_api.utils.jwt_token import generate_jwt_keypair
    from aap_gateway_api.utils.preferences import get_preference_value, update_preference_value

    if os.getenv('CI') or os.getenv('GITHUB_ACTIONS'):
        worker = os.getenv('PYTEST_XDIST_WORKER', 'main')
        print(f"ensure_jwt_keys fixture called (worker: {worker})")

    try:
        public_key = get_preference_value("proxy", "jwt_public_key", encrypted=False)
        if not public_key or public_key == '':
            # Generate keys once for the entire test session
            key_pair = generate_jwt_keypair()
            update_preference_value("proxy", "jwt_private_key", key_pair.private)
            update_preference_value("proxy", "jwt_public_key", key_pair.public)

            # Force commit the transaction to ensure keys are visible to subprocesses
            # Without this, subprocess-based service tests may not see the keys due to
            # transaction isolation, leading to JWT authentication failures
            transaction.commit()
            connection.close()  # Force connection refresh to ensure write is committed

            # Small delay to ensure database has fully committed the write
            # This addresses race conditions in subprocess startup
            time.sleep(0.1)

            if os.getenv('CI') or os.getenv('GITHUB_ACTIONS'):
                print(f"Generated new JWT keys and committed (worker: {worker})")
            public_key = key_pair.public
        else:
            if os.getenv('CI') or os.getenv('GITHUB_ACTIONS'):
                print(f"Using existing JWT keys (worker: {worker})")

        return public_key
    except Exception as e:
        # If setup fails, return None - will be handled by individual tests
        if os.getenv('CI') or os.getenv('GITHUB_ACTIONS'):
            print(f"JWT key setup failed (worker: {worker}): {e}")
        return None


@pytest.fixture
def setup_test_preferences(db, request, register_preference):
    """
    Set up the testing environment for reverting settings to their default values.
    This function performs the following steps:
        1. Registers preferences whose name specified in request.param for the 'general' section.
        2. Updates the preference values to new values to simulate changes from the default.

    Example:
        if request.param = ["fruit", "animal"]
        This will register a preference with:
            section="general"
            preference_name="fruit"
            default="fruit_default"
        And then update the preference value to "fruit_updated".
        Similarly for preference="animal"
    """
    preferences = []
    for pref_name in request.param:
        register_preference(
            section="general",
            preference_name=pref_name,
            default=f"{pref_name}_default",
            preference_type="string",
        )

        preference = Preference.objects.get(section='general', name=pref_name)

        # update the value
        preference.raw_value = f"{pref_name}_updated"
        preference.save()

        preferences.append(preference)

    yield preferences

    # no need a cleanup section here because register_preference fixture should take care of it


@pytest.fixture
def authenticator_map_factory():
    maps = []

    def _authenticator_map(authenticator=None, map_type='allow', revoke=False, team=None, organization=None, triggers={}, order=0):
        nonlocal maps
        from ansible_base.authentication.models import AuthenticatorMap

        new_map = AuthenticatorMap.objects.create(
            authenticator=authenticator, map_type=map_type, revoke=revoke, team=team, organization=organization, triggers=triggers, order=order
        )
        maps.append(new_map)
        return new_map

    yield _authenticator_map

    for map in maps:
        map.delete()


@pytest.fixture
def user_factory():
    users = []

    def _user(username, password='password', is_superuser=False, first_name='', last_name='', email=''):
        nonlocal users
        from aap_gateway_api.models import User

        new_user = User.objects.create(username=username, password=password, is_superuser=is_superuser, first_name=first_name, last_name=last_name, email=email)
        users.append(new_user)
        return new_user

    yield _user

    for usr in users:
        usr.delete()


@copy_fixture(copies=3)
@pytest.fixture
def team(randname, organization):
    from aap_gateway_api.models import Team

    random_name = randname("Test Team")
    team = Team.objects.create(name=random_name, organization=organization)
    yield team
    team.delete()


@pytest.fixture
def team_factory():
    teams = []

    def _team(name, organization, description=''):
        nonlocal teams
        from aap_gateway_api.models import Team

        new_team = Team.objects.create(name=name, organization=organization, description=description)
        teams.append(new_team)
        return new_team

    yield _team

    for t in teams:
        t.delete()


@copy_fixture(copies=3)
@pytest.fixture
def organization(randname):
    from aap_gateway_api.models import Organization

    random_name = randname("Test Organization")
    organization = Organization.objects.create(name=random_name)
    yield organization
    organization.delete()


@pytest.fixture
def organization_factory():
    orgs = []

    def _organization(name, description=''):
        nonlocal orgs
        from aap_gateway_api.models import Organization

        organization = Organization.objects.create(name=name, description=description)
        orgs.append(organization)
        return organization

    yield _organization

    for org in orgs:
        org.delete()


@pytest.fixture
def http_port(http_port_factory):
    yield http_port_factory()


@pytest.fixture
def http_api_port(http_api_port_factory):
    yield http_api_port_factory()


@pytest.fixture
def http_port_factory():
    port = None

    def _http_port():
        nonlocal port
        from aap_gateway_api.models import HTTPPort

        # Create a port with a random number. Ensure the number is not already in use.
        ports = HTTPPort.objects.all()
        port_numbers = [port.number for port in ports]
        port_number = random.randint(10000, 20000)
        while port_number in port_numbers:
            port_number = random.randint(10000, 20000)
        port = HTTPPort.objects.create(name=f"port-{port_number}", number=port_number)
        return port

    yield _http_port
    port.delete()


@pytest.fixture
def http_api_port_factory():
    def _http_api_port():
        from aap_gateway_api.models import HTTPPort

        # There can only be one API port
        api_port = HTTPPort.objects.filter(is_api_port=True).first()
        if api_port is None:
            api_port = HTTPPort()
            api_port.name = "port-9080"
            api_port.number = 9080
            api_port.is_api_port = True
            api_port.save()
        else:
            api_port.number = 9080
            api_port.save()
        return api_port

    return _http_api_port


ServiceHierarchy = namedtuple("ServiceHierarchy", ["service_cluster", "service_node", "route"])

# Hack to generate service cluster fixtures for each service type
# This will generate:
#   - service_cluster_<service_type>
#   - service_node_<service_type>
#   - additional_route_<service_type>
#   - service_api_route_<service_type>
for name in [x.value for x in DefaultServiceType]:

    def _service_type(name=name):
        st, _ = ServiceType.objects.get_or_create(name=name)
        yield st
        # Don't delete these

    def _service_cluster(name=name):
        st, _ = ServiceType.objects.get_or_create(name=name)
        cluster = ServiceCluster.objects.create(name=name, service_type=st)
        yield cluster
        cluster.delete()

    def _service_node(request, randname, name=name):  # noqa: F402
        service_cluster = request.getfixturevalue(f"service_cluster_{name}")
        node = ServiceNode.objects.create(
            name=randname("Service Node"),
            service_cluster=service_cluster,
            address=f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(0, 255)}",
        )
        yield node
        node.delete()

    def _route(request, http_port_factory, randname, name=name):  # noqa: F402
        service_cluster = request.getfixturevalue(f"service_cluster_{name}")
        randstr1 = uuid.uuid4().hex[:6]
        randstr2 = uuid.uuid4().hex[:6]
        route = AdditionalRoute.objects.create(
            name=randname("Test route"),
            http_port=http_port_factory(),
            is_service_https=False,
            service_cluster=service_cluster,
            service_port=random.randint(1000, 65536),
            service_path=f"/my-service-path-{randstr1}",
            gateway_path=f"/my-gateway-path-{randstr2}",
            description="Test route",
            envoy_cluster_name=randname("envoy cluster"),
        )
        yield route
        route.delete()

    def _service_api_route(request, http_api_port_factory, randname, name=name):  # noqa: F402
        service_cluster = request.getfixturevalue(f"service_cluster_{name}")
        randstr = uuid.uuid4().hex[:6]
        slug = f"my-api-slug-{uuid.uuid4().hex[:6]}"

        # The port for this service may be opened on localhost in order to communicate
        # with the service_test_app. This ensures that service ports won't conflict if
        # multiple test apps are launched at the same time in different pytest workers.
        # Conflicts may still occur if the developer has any ports greater than 10,000
        # open on their machine.
        port_prefixes = {
            DefaultServiceType.CONTROLLER: 1,
            DefaultServiceType.EDA: 2,
            DefaultServiceType.HUB: 3,
            DefaultServiceType.GATEWAY: 4,
        }

        port_prefix = port_prefixes[service_cluster.service_type.name]

        if pytest_worker := os.environ.get("PYTEST_XDIST_WORKER"):
            worker_num = re.sub("[^0-9]", "", pytest_worker).rjust(4, "0")
            port = int(str(port_prefix) + worker_num)
        else:
            port = int(str(port_prefix) + str(random.randint(0, 1000)).rjust(4, "0"))

        route = ServiceAPIRoute.objects.create(
            name=randname("Test API route"),
            http_port=http_api_port_factory(),
            is_service_https=False,
            service_cluster=service_cluster,
            service_port=port,
            service_path=f"/my-service-path-{randstr}",
            description="Test route",
            envoy_cluster_name=randname("envoy cluster"),
            api_slug=slug,
            gateway_path=f"/api/{slug}/",  # This is required
        )
        yield route
        route.delete()

    def _ui_plugin_route(request, http_api_port_factory, randname, name=name):  # noqa: F402
        service_cluster = request.getfixturevalue(f"service_cluster_{name}")
        randstr = uuid.uuid4().hex[:6]

        # The port for this service may be opened on localhost in order to communicate
        # with the service_test_app. This ensures that service ports won't conflict if
        # multiple test apps are launched at the same time in different pytest workers.
        # Conflicts may still occur if the developer has any ports greater than 10,000
        # open on their machine.
        port_prefixes = {
            DefaultServiceType.CONTROLLER: 1,
            DefaultServiceType.EDA: 2,
            DefaultServiceType.HUB: 3,
            DefaultServiceType.GATEWAY: 4,
        }

        port_prefix = port_prefixes[service_cluster.service_type.name]

        if pytest_worker := os.environ.get("PYTEST_XDIST_WORKER"):
            worker_num = re.sub("[^0-9]", "", pytest_worker).rjust(4, "0")
            port = int(str(port_prefix) + worker_num)
        else:
            port = int(str(port_prefix) + str(random.randint(0, 1000)).rjust(4, "0"))

        route = UIPluginRoute.objects.create(
            name=randname("Test UI Plugin route"),
            http_port=http_api_port_factory(),
            is_service_https=False,
            service_cluster=service_cluster,
            service_port=port,
            description="Test route",
            envoy_cluster_name=randname("envoy cluster"),
            ui_plugin_path=f"/plugin/{randstr}/",  # This is required
        )
        yield route
        route.delete()

    def _full_service_hierarchy(request, name=name):
        service_node = request.getfixturevalue(f"service_node_{name}")
        service_cluster = service_node.service_cluster
        route = request.getfixturevalue(f"additional_route_{name}")
        route.service_cluster = service_cluster
        route.save()
        yield ServiceHierarchy(service_cluster, service_node, route)

    globals()[f"service_type_{name}"] = pytest.fixture(_service_type)
    globals()[f"service_cluster_{name}"] = pytest.fixture(_service_cluster)
    globals()[f"service_node_{name}"] = pytest.fixture(_service_node)
    globals()[f"additional_route_{name}"] = pytest.fixture(_route)
    globals()[f"service_api_route_{name}"] = pytest.fixture(_service_api_route)
    globals()[f"ui_plugin_route_{name}"] = pytest.fixture(_ui_plugin_route)
    globals()[f"full_service_hierarchy_{name}"] = pytest.fixture(_full_service_hierarchy)


class PatchedResourceClient(GWResourceAPIClient):
    """
    Patches the resources client so that traffic is routed directly to the test service,
    rather than through envoy (which isn't available.)
    """

    def get_url_for_service(self, service):
        return f"http://localhost:{service.service_port}/api/v1/service-index/"


class PatchedAllServiceClient(AllServicesClient):
    """
    Patches the resources client so that traffic is routed directly to the test service,
    rather than through envoy (which isn't available.)
    """

    def get_url_for_service(self, service):
        return f"http://localhost:{service.service_port}/api/v1/service-index/"


@pytest.fixture
def patched_resource_client():
    with patch("aap_gateway_api.utils.resources_client.GWResourceAPIClient", PatchedResourceClient) as client:
        yield client


@pytest.fixture
def patched_load_rbac():
    with patch('aap_gateway_api.management.commands.migrate_service_data.Command.load_types_and_permissions'):
        yield


@pytest.fixture
def simulated_controller_resource_api(patched_resource_client, service_api_route_controller, ensure_jwt_keys):
    proc = launch_service("awx", service_api_route_controller.service_port, setup_fixture=None)
    yield service_api_route_controller
    proc.kill()


@pytest.fixture
def simmulated_hub_resource_api(patched_resource_client, service_api_route_hub, ensure_jwt_keys):
    proc = launch_service("galaxy", service_api_route_hub.service_port, setup_fixture=None)
    yield service_api_route_hub
    proc.kill()


@pytest.fixture
def simulated_eda_resource_api(patched_resource_client, service_api_route_eda, ensure_jwt_keys):
    proc = launch_service("eda", service_api_route_eda.service_port, setup_fixture=None)
    yield service_api_route_eda
    proc.kill()


@pytest.fixture
def system_user(db, settings, no_log_messages, django_user_model):
    # The system user should be created by the migrations so we never want to try and create it here.
    # Use all_objects manager to include managed users (system user is managed=True)
    user_obj = django_user_model.all_objects.get(username=settings.SYSTEM_USERNAME)
    yield user_obj


@pytest.fixture
def platform_auditor_user(db, django_user_model, local_authenticator):
    user = django_user_model.objects.create_user(username="platform_auditor", password="password")
    user.set_is_platform_auditor(True)
    user.save()
    return user


@pytest.fixture
def platform_auditor_api_client(db, platform_auditor_user, local_authenticator):
    client = APIClient()
    client.login(username="platform_auditor", password="password")
    yield client
    try:
        client.logout()
    except AttributeError:
        # The test might have logged the user out already (e.g. to test the logout signal)
        pass


@pytest.fixture
def keycloak_authenticator(db):
    from ansible_base.authentication.models import Authenticator

    authenticator = Authenticator.objects.create(
        name="Test Keycloak Authenticator",
        enabled=True,
        create_objects=True,
        remove_users=True,
        type="ansible_base.authentication.authenticator_plugins.keycloak",
        configuration={
            "ACCESS_TOKEN_URL": "asdf",
            "AUTHORIZATION_URL": "asdf",
            "KEY": "asdf",
            "PUBLIC_KEY": "asdf",
            "SECRET": "asdf",
        },
    )
    yield authenticator
    delete_authenticator(authenticator)


@pytest.fixture
def isolated_cache():
    """
    Provides cache access with automatic cleanup before and after each test.

    Worker isolation is handled automatically by WorkerIsolatedRedisCache backend.
    This fixture provides:
    - Test cleanup (prevents cache pollution between tests)
    - Explicit dependencies (makes cache usage clear in test signatures)
    - Future extensibility (easy to add cache setup/teardown if needed)
    """
    from django.core.cache import cache

    # Clean up before the test to ensure fresh state
    cache.clear()

    yield cache

    # Clean up after the test to prevent pollution
    cache.clear()


@pytest.fixture
def transactional_db():
    """
    Provides a transactional database for tests that need complete isolation.
    Use this for tests that modify global state or need stronger isolation guarantees.
    """
    from django.db import transaction

    # Force a transaction rollback after the test
    with transaction.atomic():
        # Create a savepoint that will be rolled back
        sid = transaction.savepoint()
        yield
        transaction.savepoint_rollback(sid)


@pytest.fixture(autouse=True)
def migrate_service_data_completed(db):
    """
    Fixture to automatically set MigrateServiceDataHasRan to True for all testing purposes.
    This allows service authentication to work in tests by marking the
    migrate_service_data command as completed.
    """
    # Mark migration as completed
    MigrateServiceDataHasRan.mark_migration_completed()


@pytest.fixture
def ca_certificate(randname):
    random_name = randname("Test CA Certificate")
    pem_data = "abcdef"
    sha256 = hashlib.sha256(pem_data.encode('utf-8')).hexdigest()
    cert = CACertificate.objects.create(name=random_name, pem_data=pem_data, sha256=sha256)
    yield cert
    cert.delete()


@pytest.fixture
def multiple_ca_certificates(randname):
    certs = []
    for certinfo in [{'name': randname('First'), 'pem_data': 'abcdef'}, {'name': randname('Second'), 'pem_data': 'xyz'}]:
        sha256 = hashlib.sha256(certinfo['pem_data'].encode('utf-8')).hexdigest()
        certs.append(CACertificate.objects.create(name=certinfo['name'], pem_data=certinfo['pem_data'], sha256=sha256))
    yield certs
    for cert in certs:
        cert.delete()
