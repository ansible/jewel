import random
import uuid
from collections import namedtuple

import pytest

from aap_gateway_api.models import AdditionalRoute, ServiceAPIRoute, ServiceCluster, ServiceNode


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
def randname():
    def _randname(prefix):
        return f"{prefix} {uuid.uuid4().hex[:6]}"

    return _randname


def copy_fixture(copies=1):
    """
    Decorator to create 'copies' copies of a fixture.

    The copies will be named func_1, func_2, ..., func_n in the same module as
    the original fixture.
    """

    def wrapper(func):
        if '_pytestfixturefunction' not in dir(func):
            raise TypeError(f"Can't apply copy_fixture to {func.__name__} because it is not a fixture. HINT: @copy_fixture must be *above* @pytest.fixture")

        module_name = func.__module__
        module = __import__(module_name, fromlist=[''])

        for i in range(copies):
            new_name = f"{func.__name__}_{i + 1}"
            setattr(module, new_name, func)
        return func

    return wrapper


@pytest.fixture
def local_authenticator(db):
    from ansible_base.authentication.models import Authenticator

    authenticator = Authenticator.objects.create(
        name="Test Local Authenticator",
        enabled=True,
        create_objects=True,
        users_unique=False,
        remove_users=True,
        type="ansible_base.authentication.authenticator_plugins.local",
        configuration={},
    )
    yield authenticator
    authenticator.authenticator_user.all().delete()
    authenticator.delete()


@pytest.fixture
def admin_api_client(db, admin_user, unauthenticated_api_client, local_authenticator):
    client = unauthenticated_api_client
    client.login(username="admin", password="password")
    yield client
    try:
        client.logout()
    except AttributeError:
        # The test might have logged the user out already (e.g. to test the logout signal)
        pass


@pytest.fixture
def user(db, django_user_model, local_authenticator):
    user = django_user_model.objects.create_user(username="user", password="password")
    yield user
    user.delete()


@pytest.fixture
def user_api_client(db, user, unauthenticated_api_client, local_authenticator):
    client = unauthenticated_api_client
    client.login(username="user", password="password")
    yield client
    try:
        client.logout()
    except AttributeError:
        # The test might have logged the user out already (e.g. to test the logout signal)
        pass


@pytest.fixture
def unauthenticated_api_client(db):
    from rest_framework.test import APIClient

    return APIClient()


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


@copy_fixture(copies=3)
@pytest.fixture
def team(randname, organization):  # noqa: F811
    from aap_gateway_api.models import Team

    random_name = randname("Test Team")
    team = Team.objects.create(name=random_name, organization=organization)
    yield team
    team.delete()


@pytest.fixture
def environment(randname):  # noqa: F811
    from aap_gateway_api.models import Environment

    random_name = randname("Test Environment")
    environment = Environment.objects.create(name=random_name)
    yield environment
    environment.delete()


@copy_fixture(copies=3)
@pytest.fixture
def organization(randname):  # noqa: F811
    from aap_gateway_api.models import Organization

    random_name = randname("Test Organization")
    organization = Organization.objects.create(name=random_name)
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
        port = HTTPPort.objects.create(name=f"port-{port_number}", number=port_number)
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
            api_port = HTTPPort()
            api_port.name = "port-9080"
            api_port.number = 9080
            api_port.is_api_port = True
            api_port.save(non_existent_user_fatal=False)
        else:
            api_port.number = 9080
            api_port.save(non_existent_user_fatal=False)
        return api_port

    yield _http_api_port
    api_port.delete()


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
            service=service_cluster,
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

    def _service_api_route(request, http_api_port_factory, randname, name=name):  # noqa: F402
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

    def _full_service_hierarchy(request, name=name):
        service_node = request.getfixturevalue(f"service_node_{name}")
        service_cluster = service_node.service
        route = request.getfixturevalue(f"additional_route_{name}")
        route.service_cluster = service_cluster
        route.save()
        yield ServiceHierarchy(service_cluster, service_node, route)

    globals()[f"service_cluster_{name}"] = pytest.fixture(_service_cluster)
    globals()[f"service_node_{name}"] = pytest.fixture(_service_node)
    globals()[f"additional_route_{name}"] = pytest.fixture(_route)
    globals()[f"service_api_route_{name}"] = pytest.fixture(_service_api_route)
    globals()[f"full_service_hierarchy_{name}"] = pytest.fixture(_full_service_hierarchy)
