from unittest.mock import MagicMock, patch

import pytest
from ansible_base.lib.utils.response import get_relative_url
from requests.exceptions import Timeout

from aap_gateway_api.models import Organization, ServiceAPIRoute, Team, User
from aap_gateway_api.utils.resources_client import AllServicesClient


class PatchedAllServicesClient(AllServicesClient):
    """
    Patches the resources client so that traffic is routed directly to the test service,
    rather than through envoy (which isn't available.)
    """

    def get_url_for_service(self, service):
        return f"http://localhost:{service.service_port}/api/v1/service-index/"


@pytest.fixture
def patched_all_services_resource_client():
    with patch("aap_gateway_api.views.api.v1.common.AllServicesClient", PatchedAllServicesClient) as client:
        yield client


def _assert_resource_identical(resource, patched_client, admin_user):
    serializer = resource.content_type.resource_type.serializer_class

    services = ServiceAPIRoute.objects.all()
    assert services.count() == 3
    for service in services:
        resource_client = patched_client(service, user=admin_user, raise_if_bad_request=True)
        gateway_data = serializer(resource.content_object).data
        service_data = resource_client.get_resource(str(resource.ansible_id)).json()

        for k in gateway_data.keys():
            assert gateway_data[k] == service_data["resource_data"][k]


def _assert_resource_deleted(resource, patched_client, admin_user):
    services = ServiceAPIRoute.objects.all()
    assert services.count() == 3
    for service in services:
        resource_client = patched_client(service, user=admin_user, raise_if_bad_request=False)
        assert resource_client.get_resource(str(resource.ansible_id)).status_code == 404


@pytest.mark.django_db(transaction=True)
def test_organizations_are_updated(
    simulated_controller_resource_api,
    simmulated_hub_resource_api,
    simulated_eda_resource_api,
    admin_user,
    admin_api_client,
    patched_resource_client,
    patched_all_services_resource_client,
    ensure_jwt_keys,
):
    org_name = "My test org"
    url = get_relative_url("organization-list")
    response = admin_api_client.post(url, data={"name": org_name})
    assert response.status_code == 201

    resource = Organization.objects.get(name=org_name).resource

    _assert_resource_identical(resource, patched_resource_client, admin_user)

    url = get_relative_url("organization-detail", kwargs={"pk": resource.object_id})
    response = admin_api_client.put(url, data={"name": "New Org Name"})
    assert response.status_code == 200

    resource.refresh_from_db()
    _assert_resource_identical(resource, patched_resource_client, admin_user)

    response = admin_api_client.delete(url)
    assert response.status_code == 204

    _assert_resource_deleted(resource, patched_resource_client, admin_user)


@pytest.mark.django_db(transaction=True)
def test_users_are_updated(
    simulated_controller_resource_api,
    simmulated_hub_resource_api,
    simulated_eda_resource_api,
    admin_user,
    admin_api_client,
    patched_resource_client,
    patched_all_services_resource_client,
):
    username = "my_username"

    url = get_relative_url("user-list")
    response = admin_api_client.post(url, data={"username": username, "password": "supersecret"})
    assert response.status_code == 201

    resource = User.objects.get(username=username).resource

    _assert_resource_identical(resource, patched_resource_client, admin_user)

    url = get_relative_url("user-detail", kwargs={"pk": resource.object_id})
    response = admin_api_client.patch(url, data={"email": "hello@aol.com", "first_name": "bob", "last_name": "bobberton"})
    assert response.status_code == 200

    resource.refresh_from_db()
    _assert_resource_identical(resource, patched_resource_client, admin_user)

    response = admin_api_client.delete(url)
    assert response.status_code == 204

    _assert_resource_deleted(resource, patched_resource_client, admin_user)


@pytest.mark.django_db(transaction=True)
def test_teams_are_updated(
    simulated_controller_resource_api,
    simmulated_hub_resource_api,
    simulated_eda_resource_api,
    admin_user,
    admin_api_client,
    patched_resource_client,
    patched_all_services_resource_client,
):
    url = get_relative_url("organization-list")
    response = admin_api_client.post(url, data={"name": "my_org_name"})
    assert response.status_code == 201
    org = response.json()

    team_name = "my cool team"

    url = get_relative_url("team-list")
    response = admin_api_client.post(url, data={"name": team_name, "organization": org["id"]})
    assert response.status_code == 201

    resource = Team.objects.get(name=team_name).resource

    _assert_resource_identical(resource, patched_resource_client, admin_user)

    url = get_relative_url("team-detail", kwargs={"pk": resource.object_id})
    response = admin_api_client.patch(url, data={"name": "hello world!"})
    assert response.status_code == 200

    resource.refresh_from_db()
    _assert_resource_identical(resource, patched_resource_client, admin_user)

    response = admin_api_client.delete(url)
    assert response.status_code == 204

    _assert_resource_deleted(resource, patched_resource_client, admin_user)


@pytest.mark.django_db
def test_all_services_client_with_service_filter(
    simulated_controller_resource_api,
    simmulated_hub_resource_api,
    simulated_eda_resource_api,
    admin_user,
):
    """Test that service_filter parameter correctly filters services"""
    # Get one specific service to filter on
    controller_service = ServiceAPIRoute.objects.filter(service_cluster__service_type__name="controller").first()
    assert controller_service is not None

    client = PatchedAllServicesClient(user=admin_user, service_filter={"service_cluster__service_type__name": "controller"})

    # Make a request with filtering enabled
    with patch.object(client, '_make_service_request') as mock_request:
        mock_request.return_value = (controller_service.pk, MagicMock(status_code=200))
        client._make_request("GET", "/test/")

        # Should only be called once (for controller, not hub or eda)
        assert mock_request.call_count == 1


@pytest.mark.django_db
def test_all_services_client_async_returns_immediately(
    simulated_controller_resource_api,
    simmulated_hub_resource_api,
    simulated_eda_resource_api,
    admin_user,
):
    """wait_for_response=False returns empty dict immediately without waiting."""
    client = PatchedAllServicesClient(user=admin_user, wait_for_response=False)

    mock_executor = MagicMock()
    with patch('aap_gateway_api.utils.resources_client._get_executor', return_value=mock_executor):
        responses = client._make_request("GET", "/test/")

    assert responses == {}
    expected_count = (
        ServiceAPIRoute.objects.exclude(service_cluster__service_type__name="gateway")
        .exclude(service_cluster__service_type__service_index_path__isnull=True)
        .exclude(service_cluster__service_type__service_index_path='')
        .count()
    )
    assert mock_executor.submit.call_count == expected_count


@pytest.mark.django_db
def test_all_services_client_timeout_raises_when_wait_for_response_true(
    simulated_controller_resource_api,
    simmulated_hub_resource_api,
    simulated_eda_resource_api,
    admin_user,
):
    """Timeout exceptions are raised when wait_for_response=True."""
    client = PatchedAllServicesClient(user=admin_user, wait_for_response=True)

    with patch.object(type(client), 'jwt', new_callable=lambda: MagicMock(return_value="fake-jwt-token")):
        with patch('aap_gateway_api.utils.resources_client.requests.request') as mock_request:
            mock_request.side_effect = Timeout("Request timed out")

            with pytest.raises(Timeout):
                client._make_request("GET", "/test/")


@pytest.mark.django_db
def test_all_services_client_sync_callback(
    simulated_controller_resource_api,
    simmulated_hub_resource_api,
    simulated_eda_resource_api,
    admin_user,
):
    """Callback is invoked for each service response in the synchronous path."""
    callback_calls = []

    def test_callback(service, response):
        callback_calls.append((service.pk, response))

    client = PatchedAllServicesClient(user=admin_user).with_callback(test_callback)

    with patch('aap_gateway_api.utils.resources_client.requests.request') as mock_request:
        mock_response = MagicMock(status_code=200)
        mock_request.return_value = mock_response

        responses = client._make_request("GET", "/test/")

        expected_count = (
            ServiceAPIRoute.objects.exclude(service_cluster__service_type__name="gateway")
            .exclude(service_cluster__service_type__service_index_path__isnull=True)
            .exclude(service_cluster__service_type__service_index_path='')
            .count()
        )
        assert len(callback_calls) == expected_count
        for service_pk, response in callback_calls:
            assert response == responses[service_pk]
            if response is not None:
                assert response.status_code == 200


@pytest.mark.django_db
def test_all_services_client_sync_exception_handling(
    simulated_controller_resource_api,
    simmulated_hub_resource_api,
    simulated_eda_resource_api,
    admin_user,
):
    """Exceptions in synchronous path are caught and logged, responses set to None."""
    client = PatchedAllServicesClient(user=admin_user)

    with patch('aap_gateway_api.utils.resources_client.requests.request') as mock_request:
        mock_request.side_effect = Exception("Something went wrong")

        responses = client._make_request("GET", "/test/")

        assert all(response is None for response in responses.values())
        expected_count = (
            ServiceAPIRoute.objects.exclude(service_cluster__service_type__name="gateway")
            .exclude(service_cluster__service_type__service_index_path__isnull=True)
            .exclude(service_cluster__service_type__service_index_path='')
            .count()
        )
        assert len(responses) == expected_count
