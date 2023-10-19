import random
import uuid

import pytest

from aap_gateway_api.models import AdditionalRoute, ServiceAPIRoute, ServiceCluster, ServiceNode
from ansible_base.tests.conftest import admin_api_client, local_authenticator, shut_up_logging, unauthenticated_api_client, user  # noqa: F401


def copy_fixture(copies=1):
    """
    Decorator to create 'copies' copies of a fixture.

    The copies will be named func_1, func_2, ..., func_n in the same module as
    the original fixture.
    """

    def wrapper(func):
        if '_pytestfixturefunction' not in dir(func):
            raise TypeError(f"Can't apply copy_fixture to {func.__name__} because it is not a fixture. HINT: @copy_fixture must be *above* @pytest.fixture")
        for i in range(copies):
            new_name = f"{func.__name__}_{i + 1}"
            globals()[new_name] = func
        return func

    return wrapper


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
        port = HTTPPort.objects.create(number=port_number)
        return port

    yield _http_port
    port.delete()


@pytest.fixture
def http_api_port_factory():
    api_port = None

    def _http_api_port():
        nonlocal api_port
        from aap_gateway_api.models import HTTPPort

        # There can only be one API port
        api_port = HTTPPort.objects.filter(is_api_port=True).first()
        if api_port is None:
            api_port = HTTPPort.objects.create(number=9080, is_api_port=True)
        else:
            api_port.number = 9080
            api_port.save()
        return api_port

    yield _http_api_port
    api_port.delete()


# Hack to generate service cluster fixtures for each service type
# This will generate:
#   - service_cluster_<service_type>
#   - service_node_<service_type>
#   - additional_route_<service_type>
#   - service_api_route_<service_type>
for shortname, name in dict(ServiceCluster.ServiceType.choices).items():

    def _service_cluster(shortname=shortname):
        cluster = ServiceCluster.objects.create(service_type=shortname)
        yield cluster
        cluster.delete()

    def _service_node(request):
        service_cluster = request.getfixturevalue(f"service_cluster_{name}")
        node = ServiceNode.objects.create(
            service=service_cluster,
            address=f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(0, 255)}",
        )
        yield node
        node.delete()

    def _route(request, http_port_factory, randname):
        service_cluster = request.getfixturevalue(f"service_cluster_{name}")
        randstr1 = uuid.uuid4().hex[:6]
        randstr2 = uuid.uuid4().hex[:6]
        route = AdditionalRoute.objects.create(
            name=randname("Test route"),
            port=http_port_factory(),
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

    def _service_api_route(request, http_api_port_factory, randname):
        service_cluster = request.getfixturevalue(f"service_cluster_{name}")
        randstr = uuid.uuid4().hex[:6]
        slug = f"my-api-slug-{uuid.uuid4().hex[:6]}"
        route = ServiceAPIRoute.objects.create(
            name=randname("Test API route"),
            port=http_api_port_factory(),
            is_service_https=False,
            service_cluster=service_cluster,
            service_port=random.randint(1000, 65536),
            service_path=f"/my-service-path-{randstr}",
            description="Test route",
            envoy_cluster_name=randname("envoy cluster"),
            api_slug=slug,
            gateway_path=f"/api/{slug}/",  # This is required
        )
        yield route
        route.delete()

    globals()[f"service_cluster_{name}"] = pytest.fixture(_service_cluster)
    globals()[f"service_node_{name}"] = pytest.fixture(_service_node)
    globals()[f"additional_route_{name}"] = pytest.fixture(_route)
    globals()[f"service_api_route_{name}"] = pytest.fixture(_service_api_route)
