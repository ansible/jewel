from http import HTTPStatus
from unittest.mock import patch

import pytest
from ansible_base.authentication.models import AuthenticatorUser
from requests import Response, exceptions

from aap_gateway_api.authentication.authenticator_plugins.legacy_sso import AuthenticatorPlugin
from aap_gateway_api.models.user import User
from aap_gateway_api.tests.conftest import PatchedResourceClient


@pytest.mark.django_db(transaction=True)
def test_moving_authenticator_user(user_factory, create_user, local_authenticator, resource_client, api_slugs):

    # create_user creates user but does not attempt to delete it at the end of test, like user_factory does
    old_u = create_user("old_one")
    new_u = user_factory("new_one")

    old_authenticator_user = AuthenticatorUser.objects.create(provider=local_authenticator, user=old_u, uid=old_u.username)
    old_u_ansible_id = old_u.resource.ansible_id

    # by patching the delete_resource method below no API calls will be made
    with patch.object(resource_client, "delete_resource") as delete_resource_method:
        auth_plugin = AuthenticatorPlugin()
        auth_plugin.move_authenticator_user_to(new_u, old_authenticator_user)
        delete_resource_method.assert_called_with(ansible_id=old_u_ansible_id)

    assert not User.objects.filter(username="old_one").exists()


@pytest.mark.django_db(transaction=True)
def test_moving_already_linked_user(user_factory, local_authenticator, resource_client, api_slugs):

    # in this test the user wont be removed, we can use user_factory
    old_u = user_factory("old_one")
    new_u = user_factory("new_one")

    old_authenticator_user = AuthenticatorUser.objects.create(provider=local_authenticator, user=old_u, uid=old_u.username)

    # by patching the delete_resource method below no API calls will be made
    with patch.object(resource_client, "delete_resource"):
        with patch(
            "ansible_base.authentication.authenticator_plugins.base.AbstractAuthenticatorPlugin.move_authenticator_user_to"
        ) as super_move_authenticator_user_to_method:
            # setting return value from super method to be None to indicate user was already linked
            super_move_authenticator_user_to_method.return_value = None
            auth_plugin = AuthenticatorPlugin()
            auth_plugin.move_authenticator_user_to(new_u, old_authenticator_user)

    assert User.objects.filter(username="old_one").exists()


@pytest.mark.django_db(transaction=True)
def test_moving_authenticator_user_with_nonexisting_services(user_factory, create_user, local_authenticator):

    # create_user creates user but does not attempt to delete it at the end of test, like user_factory does
    old_u = create_user("old_one")
    new_u = user_factory("new_one")

    old_authenticator_user = AuthenticatorUser.objects.create(provider=local_authenticator, user=old_u, uid=old_u.username)

    auth_plugin = AuthenticatorPlugin()
    auth_plugin.move_authenticator_user_to(new_u, old_authenticator_user)

    assert not User.objects.filter(username="old_one").exists()


# the resource client and simulated resource api fixtures are needed to start actual services
@pytest.mark.django_db(transaction=True)
def test_moving_authenticator_user_with_API_calls(
    user_factory, create_user, local_authenticator, api_slugs, resource_client, simulated_controller_resource_api, simmulated_hub_resource_api
):

    # create_user creates user but does not attempt to delete it at the end of test, like user_factory does
    old_u = create_user("old_one")
    new_u = user_factory("new_one")

    old_authenticator_user = AuthenticatorUser.objects.create(provider=local_authenticator, user=old_u, uid=old_u.username)

    auth_plugin = AuthenticatorPlugin()
    auth_plugin.move_authenticator_user_to(new_u, old_authenticator_user)

    assert not User.objects.filter(username="old_one").exists()


@pytest.mark.django_db(transaction=True)
def test_moving_authenticator_user_with_API_error(user_factory, create_user, local_authenticator, resource_client, api_slugs):

    # create_user creates user but does not attempt to delete it at the end of test, like user_factory does
    old_u = create_user("old_one")
    new_u = user_factory("new_one")

    old_authenticator_user = AuthenticatorUser.objects.create(provider=local_authenticator, user=old_u, uid=old_u.username)

    # by patching the delete_resource method below no API calls will be made and we can make it raise an error
    with patch.object(resource_client, "delete_resource") as delete_resource_method:
        http_response = Response()
        http_response.status_code = HTTPStatus.INTERNAL_SERVER_ERROR
        delete_resource_method.side_effect = exceptions.HTTPError("something bad happened", response=http_response)
        auth_plugin = AuthenticatorPlugin()
        with pytest.raises(exceptions.HTTPError) as e:
            auth_plugin.move_authenticator_user_to(new_u, old_authenticator_user)
            assert str(e) == "something bad happened"


@pytest.fixture
def api_slugs(service_api_route_controller, service_api_route_hub):
    with patch(
        "aap_gateway_api.authentication.authenticator_plugins.base._API_SLUGS", [service_api_route_controller.api_slug, service_api_route_hub.api_slug]
    ) as mocked_api_slugs:
        yield mocked_api_slugs


@pytest.fixture
def resource_client():
    with patch("aap_gateway_api.authentication.authenticator_plugins.base.GWResourceAPIClient", PatchedResourceClient) as patched_resource_client:
        yield patched_resource_client


@pytest.fixture
def create_user():
    def _create_user_factory(username: str) -> User:
        return User.objects.create(username=username, password="password", is_superuser=False)

    return _create_user_factory
