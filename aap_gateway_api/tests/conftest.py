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
from ansible_base.lib.testing.util import copy_fixture  # noqa: F401

from aap_gateway_api.models import AdditionalRoute, ServiceAPIRoute, ServiceCluster, ServiceNode, User
from aap_gateway_api.tests.service_test_app.launch import launch_service
from aap_gateway_api.utils.resources_client import GWResourceAPIClient


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
        kwargs_cache.update(kwargs)
        ret = register(**kwargs)
        key = get_preference_key(kwargs["section"], kwargs["preference_name"])
        gateway_preference_registry.manager()[key]  # Register the preference in the database
        return ret

    yield _register_preference
    del gateway_preference_registry[kwargs_cache["section"]][kwargs_cache["preference_name"]]
    Preference.objects.filter(section=kwargs_cache["section"], name=kwargs_cache["preference_name"]).delete()


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
for shortname, name in dict(ServiceCluster.ServiceType.choices).items():

    def _service_cluster(shortname=shortname):
        cluster = ServiceCluster.objects.create(name=shortname, service_type=shortname)
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
            ServiceCluster.ServiceType.CONTROLLER: 1,
            ServiceCluster.ServiceType.EDA: 2,
            ServiceCluster.ServiceType.HUB: 3,
            ServiceCluster.ServiceType.GATEWAY: 4,
        }

        port_prefix = port_prefixes[service_cluster.service_type]

        if pytest_worker := os.environ.get("PYTEST_XDIST_WORKER"):
            worker_num = re.sub("[^0-9]", "", pytest_worker).rjust(4, "0")
            port = int(str(port_prefix) + worker_num)
        else:
            port = int(str(port_prefix) + str(str(random.randint(0, 1000)).rjust(4, "0")))

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

    def _full_service_hierarchy(request, name=name):
        service_node = request.getfixturevalue(f"service_node_{name}")
        service_cluster = service_node.service_cluster
        route = request.getfixturevalue(f"additional_route_{name}")
        route.service_cluster = service_cluster
        route.save()
        yield ServiceHierarchy(service_cluster, service_node, route)

    globals()[f"service_cluster_{name}"] = pytest.fixture(_service_cluster)
    globals()[f"service_node_{name}"] = pytest.fixture(_service_node)
    globals()[f"additional_route_{name}"] = pytest.fixture(_route)
    globals()[f"service_api_route_{name}"] = pytest.fixture(_service_api_route)
    globals()[f"full_service_hierarchy_{name}"] = pytest.fixture(_full_service_hierarchy)


class PatchedResourceClient(GWResourceAPIClient):
    """
    Patches the resources client so that traffic is routed directly to the test service,
    rather than through envoy (which isn't available.)
    """

    def __init__(self, service, **kwargs):
        super().__init__(service, **kwargs)

        self.base_url = f"http://localhost:{service.service_port}/api/v1/service-index/"


@pytest.fixture
def patched_resource_client():
    with patch("aap_gateway_api.utils.resources_client.GWResourceAPIClient", PatchedResourceClient) as client:
        yield client


@pytest.fixture
def simulated_controller_resource_api(patched_resource_client, service_api_route_controller):
    proc = launch_service("awx", service_api_route_controller.service_port, setup_fixture=None)
    yield service_api_route_controller
    proc.kill()


@pytest.fixture
def simmulated_hub_resource_api(patched_resource_client, service_api_route_hub):
    proc = launch_service("galaxy", service_api_route_hub.service_port, setup_fixture=None)
    yield service_api_route_hub
    proc.kill()


@pytest.fixture
def simulated_eda_resource_api(patched_resource_client, service_api_route_eda):
    proc = launch_service("eda", service_api_route_eda.service_port, setup_fixture=None)
    yield service_api_route_eda
    proc.kill()


@pytest.fixture
def system_user(db, settings, no_log_messages):
    with no_log_messages():
        user_obj, _created = User.objects.get_or_create(username=settings.SYSTEM_USERNAME)
    yield user_obj
