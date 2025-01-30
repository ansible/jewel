import uuid
from datetime import datetime, timedelta
from unittest import mock

import jwt
import pytest
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.resource_registry.models import service_id
from rest_framework.test import APIClient

from aap_gateway_api.models import ServiceKey


def _create_jwt(user, key, additional_payload=None, service=None, expiration=60):
    if additional_payload is None:
        additional_payload = {}
    if service is None:
        service = service_id()

    payload = {"sub": str(user.resource.ansible_id), "iss": str(service), "exp": datetime.now() + timedelta(seconds=expiration), **additional_payload}

    return jwt.encode(payload, key.secret, key.algorithm)


def _create_jwt_system_user(key, additional_payload=None, service=None, expiration=60):
    if additional_payload is None:
        additional_payload = {}
    if service is None:
        service = service_id()

    payload = {"iss": str(service), "exp": datetime.now() + timedelta(seconds=expiration), **additional_payload}

    return jwt.encode(payload, key.secret, key.algorithm)


def _get_client(token):
    return APIClient(headers={"X-ANSIBLE-SERVICE-AUTH": token})


def _set_up_service_key(service, service_id):
    service.service_id = service_id
    service.save()
    return service.generate_key()


@pytest.fixture
def service_jwt_token(user, service_cluster_gateway):
    key = _set_up_service_key(service_cluster_gateway, service_id())

    return _create_jwt(user, key)


@pytest.fixture
def service_jwt_token_system_user(system_user, service_cluster_gateway):
    key = _set_up_service_key(service_cluster_gateway, service_id())

    return _create_jwt_system_user(key)


@pytest.fixture
def service_jwt_client(service_jwt_token) -> APIClient:
    return _get_client(service_jwt_token)


@pytest.fixture
def service_jwt_client_system_user(service_jwt_token_system_user) -> APIClient:
    return _get_client(service_jwt_token_system_user)


@pytest.mark.django_db
def test_authentication(service_jwt_client, user):
    url = get_relative_url("resource-list")
    resp = service_jwt_client.get(url)
    assert resp.status_code == 200
    assert resp.wsgi_request.user == user


@pytest.mark.django_db
def test_authentication_system_user(service_jwt_client_system_user, system_user):
    url = get_relative_url("resource-list")
    resp = service_jwt_client_system_user.get(url)
    assert resp.status_code == 200
    assert resp.wsgi_request.user == system_user


@pytest.mark.django_db
def test_multiple_active_keys(service_cluster_gateway, user, service_jwt_client):
    service_cluster_gateway.generate_key(mark_previous_inactive=False)
    url = get_relative_url("resource-list")
    resp = service_jwt_client.get(url)
    assert resp.status_code == 200
    assert resp.wsgi_request.user == user


@pytest.mark.django_db
def test_deactivate_key(service_cluster_gateway, user, service_jwt_client):
    service_cluster_gateway.generate_key()
    url = get_relative_url("resource-list")
    resp = service_jwt_client.get(url)
    assert resp.status_code == 401


@pytest.mark.django_db
@pytest.mark.parametrize(
    'service_cluster',
    [
        'service_cluster_eda',
        'service_cluster_hub',
        'service_cluster_controller',
    ],
)
def test_resource_api_access(user, service_cluster, request):
    id = uuid.uuid4()
    key = _set_up_service_key(request.getfixturevalue(service_cluster), id)
    jwt = _create_jwt(
        user,
        key,
        service=id,
    )
    client = _get_client(jwt)

    url = get_relative_url("resource-list")
    resp = client.get(url)
    assert resp.status_code == 200

    data = {
        "resource_type": "shared.organization",
        "resource_data": {"name": "my_new_org"},
    }
    resp = client.post(url, data, format="json")
    assert resp.status_code == 201

    # Check that the token can't be used for the rest of the Gateway API since the
    # user has not authorized access to the service
    url = get_relative_url("me-list")
    resp = client.get(url)
    assert resp.status_code == 401


@pytest.mark.django_db
@pytest.mark.parametrize(
    'token_data',
    [
        {"payload": {"sub": str(uuid.uuid4())}},
        {"payload": {"iss": str(uuid.uuid4())}},
        {"payload": {"exp": datetime.now() + timedelta(seconds=-5)}},
        {"key": "bad key"},
        {"algorithm": "HS512"},
    ],
)
def test_invalid_jwt_schema(service_cluster_gateway, user, token_data):
    # TODO
    key = _set_up_service_key(service_cluster_gateway, service_id())

    payload = {
        "sub": str(user.resource.ansible_id),
        "iss": str(service_cluster_gateway.service_id),
        "exp": datetime.now() + timedelta(seconds=60),
        **token_data.get("payload", {}),
    }
    secret = token_data.get("key", key.secret)
    algorithm = token_data.get("algorithm", key.algorithm)

    client = _get_client(jwt.encode(payload, secret, algorithm))

    url = get_relative_url("resource-list")
    resp = client.get(url)
    assert resp.status_code == 401


@pytest.mark.django_db
def test_token_is_not_jwt(service_jwt_token):
    client = _get_client(service_jwt_token)
    url = get_relative_url("resource-list")
    resp = client.get(url)
    assert resp.status_code == 200

    client = _get_client("akfdjjfdlajsdflkjasdflkjasfdkljasdflkj")
    url = get_relative_url("resource-list")
    resp = client.get(url)
    assert resp.status_code == 401


@pytest.mark.django_db
def test_delete_inactive_keys(service_cluster_gateway):
    assert ServiceKey.objects.count() == 0

    service_cluster_gateway.generate_key()
    assert ServiceKey.objects.count() == 1
    assert ServiceKey.objects.filter(is_active=True).count() == 1

    service_cluster_gateway.generate_key()
    assert ServiceKey.objects.count() == 2
    assert ServiceKey.objects.filter(is_active=True).count() == 1

    service_cluster_gateway.generate_key(mark_previous_inactive=False)
    assert ServiceKey.objects.count() == 3
    assert ServiceKey.objects.filter(is_active=True).count() == 2

    service_cluster_gateway.delete_inactive_keys()
    assert ServiceKey.objects.filter(is_active=False).count() == 0
    assert ServiceKey.objects.filter(is_active=True).count() == 2


@pytest.mark.django_db
def test_generate_service_key_api(user_api_client, admin_api_client, service_cluster_eda):
    url = get_relative_url("service_key-list")
    data = {"service_cluster": service_cluster_eda.pk, "mark_previous_inactive": True}

    # Check that unprivileged users can't generate new keys.
    resp = user_api_client.post(url, data, format="json")
    assert resp.status_code == 403
    assert ServiceKey.objects.count() == 0

    resp = admin_api_client.post(url, data, format="json")
    assert resp.status_code == 201
    assert ServiceKey.objects.filter(service_cluster=service_cluster_eda).count() == 1

    key = ServiceKey.objects.first()
    assert resp.json()["secret"] == key.secret


@pytest.mark.django_db
def test_service_key_api(user_api_client, admin_api_client, service_cluster_eda):
    key_list = get_relative_url("service_key-list")
    key = service_cluster_eda.generate_key()

    # Check that unprivileged users can't access the keys api.
    resp = user_api_client.get(key_list)
    assert resp.status_code == 403

    resp = admin_api_client.get(key_list)
    assert resp.status_code == 200

    for serialized in resp.json()["results"]:
        serialized["secret"] == "$encrypted$"

    detail = get_relative_url("service_key-detail", kwargs={"pk": key.pk})

    resp = user_api_client.get(detail)
    assert resp.status_code == 403

    resp = admin_api_client.get(detail)
    assert resp.status_code == 200
    assert resp.json()["secret"] == "$encrypted$"

    resp = admin_api_client.patch(detail, {"is_active": False}, format="json")
    assert resp.status_code == 200

    resp = admin_api_client.delete(detail)
    assert resp.status_code == 204


def test_bad_path_info(expected_log):
    from aap_gateway_api.authentication.service_token_auth import ServiceTokenAuthentication

    token_auth = ServiceTokenAuthentication()
    token_auth.authorized_paths = ['testing']

    request = mock.Mock()
    request.path = '/junk'

    with expected_log('aap_gateway_api.authentication.service_token_auth.logger', 'error', 'Invalid tuple in authorized_paths'):
        token_auth.is_user_authorized(request, None, None, None)


def test_failed_lookup(expected_log):
    from aap_gateway_api.authentication.service_token_auth import ServiceTokenAuthentication

    token_auth = ServiceTokenAuthentication()
    token_auth.authorized_paths = [('junk', {}, [])]

    request = mock.Mock()
    request.path = '/junk'

    with expected_log('aap_gateway_api.authentication.service_token_auth.logger', 'warning', 'Unable to get relative url for'):
        token_auth.is_user_authorized(request, None, None, None)


@pytest.mark.parametrize(
    "allowed_methods,call_method,expected_result",
    [
        ([], 'GET', False),
        (['get'], 'GET', True),
        (['get', 'POST', 'head'], 'delete', False),
        (['get', 'POST', 'head'], 'HEAD', True),
    ],
)
def test_validate_methods(allowed_methods, call_method, expected_result):
    from aap_gateway_api.authentication.service_token_auth import ServiceTokenAuthentication

    token_auth = ServiceTokenAuthentication()
    token_auth.authorized_paths = [('junk', {}, allowed_methods)]

    request = mock.Mock()
    request.path = '/junk'
    request.method = call_method

    with mock.patch('aap_gateway_api.authentication.service_token_auth.get_relative_url', side_effect=['/resource_api', '/junk']):
        assert token_auth.is_user_authorized(request, None, None, None) == expected_result
