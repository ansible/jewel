from datetime import datetime, timedelta
from unittest.mock import patch

import jwt
import pytest
import requests
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.resource_registry.models import service_id
from django.core.management import call_command
from rest_framework.test import APIClient

from aap_gateway_api.models import MigratedAuthenticatorMetadata, User
from aap_gateway_api.tests.conftest import PatchedAllServiceClient, PatchedResourceClient
from aap_gateway_api.tests.service_test_app.fixtures.data.legacy_auth import Account, get_user_set
from aap_gateway_api.tests.service_test_app.launch import launch_service
from aap_gateway_api.utils.resources_client import ResourceRequestBody

UP_TO_DOWN = {
    "controller": "awx",
    "hub": "galaxy",
    "eda": "eda",
}

DOWN_TO_UP = {
    "awx": "controller",
    "galaxy": "hub",
    "eda": "eda",
}


class AuthClient:
    def __init__(self, service_routes):
        self.client = APIClient()
        self.service_routes = service_routes

    def auth_sso(self, account: Account, service):
        url = get_relative_url("legacy_auth-authenticate-sso")
        service_api = self.service_routes[service]

        resp = requests.get(
            f"http://localhost:{service_api.service_port}/sso/?username={account.username}&backend={account.backend.backend}",
            allow_redirects=False,
        )

        # The gateway API isn't actually running on localhost so we'll intercept the redirect and handle it manually.
        redirect = resp.headers["Location"]
        auth_code = redirect.split("?auth_code=", maxsplit=1)[1]

        return self.client.get(f"{url}?auth_code={auth_code}", follow=True)

    def auth_password(self, account: Account, service_type):
        url = get_relative_url("legacy_auth-authenticate-password")
        return self.client.post(
            url,
            data={
                "username": account.username,
                "password": account.password,
                "service_type": service_type,
            },
            follow=True,
        )

    def finalize(self, new_username=None):
        url = get_relative_url("legacy_auth-finalize")
        data = {"new_username": new_username}
        if new_username is None:
            data.pop("new_username")
        return self.client.post(url, data=data, format="json", follow=True)

    def reset(self):
        url = get_relative_url("legacy_auth-reset")
        return self.client.post(url, data={}, format="json", follow=True)

    def current_state(self):
        url = get_relative_url("legacy_auth-list")
        return self.client.get(url)


class TestLegacyAuth:
    @pytest.fixture
    def patched_legacy_auth_client(self):
        with patch("aap_gateway_api.views.api.v1.legacy_auth.GWResourceAPIClient", PatchedResourceClient) as client:
            yield client

    @pytest.fixture
    def patched_utils_resource_client(self):
        with patch("aap_gateway_api.utils.user_migration.GWResourceAPIClient", PatchedResourceClient) as client:
            yield client

    @pytest.fixture
    def services(
        self,
        service_api_route_controller,
        service_api_route_eda,
        service_api_route_hub,
        patched_resource_client,
        patched_legacy_auth_client,
        patched_utils_resource_client,
        admin_user,
    ):
        hub_key = service_api_route_hub.service_cluster.generate_key()
        eda_key = service_api_route_eda.service_cluster.generate_key()
        controller_key = service_api_route_controller.service_cluster.generate_key()

        awx = launch_service("awx", service_api_route_controller.service_port, "legacy_auth", secret_key=controller_key.secret, save_std=False)
        galaxy = launch_service("galaxy", service_api_route_hub.service_port, "legacy_auth", secret_key=hub_key.secret, save_std=False)
        eda = launch_service("eda", service_api_route_eda.service_port, "legacy_auth", secret_key=eda_key.secret, save_std=False)

        cmd_kwargs = {
            "username": admin_user.username,
            "merge_teams": True,
            "merge_organizations": True,
            "merge_users": False,
        }

        call_command("migrate_service_data", api_slug=service_api_route_controller.api_slug, **cmd_kwargs)
        call_command("migrate_service_data", api_slug=service_api_route_hub.api_slug, **cmd_kwargs)
        call_command("migrate_service_data", api_slug=service_api_route_eda.api_slug, **cmd_kwargs)

        yield (service_api_route_controller, service_api_route_eda, service_api_route_hub)

        awx.kill()
        galaxy.kill()
        eda.kill()

    @pytest.mark.django_db(transaction=True)
    def test_all_legacy_auth(self, services, subtests):
        """
        All of the tests in this class will be run through this test. While this is not proper form
        for pytest, there are two reasons to do it this way:

        1. The "services" fixture needs to spin up 3 lightweight instances of the service_test_app.
           This is somewhat expensive operation, and the fixture used here is intented to be used
           across multiple tests in order to fully mimic how the legacy auth endpoint will be used
           in production.
        2. We want to persist the state of the django DB across multiple test runs. This is to verify
           that we aren't creating any conflicts as users login and are migrated into the Gateway.
        """
        awx_svc, eda_svc, galaxy_svc = services

        service_routes = {
            "awx": awx_svc,
            "eda": eda_svc,
            "galaxy": galaxy_svc,
        }

        for attr in dir(self):
            if attr.startswith("subtest"):
                with subtests.test(msg=attr):
                    getattr(self, attr)(AuthClient(service_routes))

    def subtest_merging_all_accounts_controller_oidc(self, client: AuthClient):
        user_set = get_user_set("controller_oidc")
        self._test_merge_multiple_accounts(client, user_set, ("awx", "galaxy", "eda"), user_set["awx"].username, False)

    def subtest_merging_all_accounts_hub_keycloak(self, client: AuthClient):
        user_set = get_user_set("hub_keycloak")
        self._test_merge_multiple_accounts(client, user_set, ("awx", "galaxy", "eda"), user_set["awx"].username, False)

    def subtest_merging_all_accounts_controller_saml(self, client: AuthClient):
        user_set = get_user_set("controller_saml")
        self._test_merge_multiple_accounts(client, user_set, ("awx", "galaxy", "eda"), user_set["awx"].username, False)

    def subtest_merging_all_accounts_different_pass(self, client: AuthClient):
        user_set = get_user_set("password_set_1")
        self._test_merge_multiple_accounts(client, user_set, ("awx", "galaxy", "eda"), user_set["awx"].username, False)

    def subtest_merging_all_accounts_same_pass(self, client: AuthClient):
        user_set = get_user_set("password_set_2")
        self._test_merge_multiple_accounts(client, user_set, ("awx", "galaxy", "eda"), user_set["awx"].username, False)

    def subtest_merging_all_accounts_galaxy_first(self, client: AuthClient):
        user_set = get_user_set("password_set_3")
        username = client.service_routes["galaxy"].api_slug + ":" + user_set["galaxy"].username
        self._test_merge_multiple_accounts(client, user_set, ("galaxy", "awx", "eda"), username, True)

    def subtest_merging_all_accounts_eda_first(self, client: AuthClient):
        user_set = get_user_set("password_set_4")
        username = client.service_routes["eda"].api_slug + ":" + user_set["eda"].username
        self._test_merge_multiple_accounts(
            client,
            user_set,
            (
                "eda",
                "galaxy",
                "awx",
            ),
            username,
            True,
        )

    def subtest_merging_all_accounts_conflict_all_eda_first(self, client: AuthClient):
        user_set = get_user_set("conflict_all1")
        username = client.service_routes["eda"].api_slug + ":" + user_set["eda"].username
        self._test_merge_multiple_accounts(
            client,
            user_set,
            (
                "eda",
                "galaxy",
                "awx",
            ),
            username,
            True,
        )

    def subtest_merging_all_accounts_conflict_all_hub_first(self, client: AuthClient):
        user_set = get_user_set("conflict_all2")
        username = client.service_routes["galaxy"].api_slug + ":" + user_set["galaxy"].username
        self._test_merge_multiple_accounts(
            client,
            user_set,
            (
                "galaxy",
                "eda",
                "awx",
            ),
            username,
            True,
        )

    def subtest_merging_all_accounts_conflict_all_awx_first(self, client: AuthClient):
        user_set = get_user_set("conflict_all3")
        username = user_set["awx"].username
        self._test_merge_multiple_accounts(
            client,
            user_set,
            (
                "awx",
                "eda",
                "galaxy",
            ),
            username,
            False,
        )

    def subtest_rename_and_fail_double_link_and_link_multiple(self, client: AuthClient):
        user_set_1 = get_user_set("already_linked1")
        user_set_2 = get_user_set("already_linked2")
        user_set_3 = get_user_set("already_linked3")

        self._test_merge_multiple_accounts(client, user_set_1, ("awx", "galaxy"), user_set_1["awx"].username, False)

        # Check that we can't link another hub account
        response = client.auth_password(user_set_2["galaxy"], service_type="hub")
        assert response.status_code == 400

        # Reset the client session
        resp = client.reset()
        assert resp.status_code == 200

        resp = client.current_state()
        assert resp.data["username"] == ""

        # login with the EDA account
        resp = client.auth_password(user_set_3["eda"], "eda")
        assert resp.status_code == 200
        new_username = user_set_3["eda"].username + "renamed"

        # Check that account renaming works
        assert client.finalize().status_code == 400
        resp = client.finalize(new_username=new_username)
        self._assert_me_username(client, new_username)

        # login with our initial set of already migrated accounts to try and hook them up to the
        # new EDA account.
        resp = client.auth_password(user_set_1["galaxy"], "hub")
        data = resp.data

        assert resp.status_code == 200

        # Check that all three accounts have been linked.
        combined_user_set = {**user_set_1, **user_set_3}
        assert len(data["linked_accounts"]) == 3
        self._assert_linked_accounts(data, combined_user_set, ("awx", "galaxy", "eda"))
        self._assert_me_username(client, new_username)

    def subtest_link_accounts_with_completely_different_usernames(self, client: AuthClient):
        user_set = get_user_set("different_uesernames")
        self._test_merge_multiple_accounts(
            client,
            user_set,
            (
                "galaxy",
                "eda",
                "awx",
            ),
            user_set["galaxy"].username,
            False,
            username_for="galaxy",
        )

    def subtest_fail_invalid_password(self, client: AuthClient):
        bad_password = Account(None, None, None, "bad password", username="user1")
        assert client.auth_password(bad_password, "controller").status_code == 400

        bad_username = Account(None, None, None, "pass", username="IDoNotExist")
        assert client.auth_password(bad_username, "controller").status_code == 400

    def subtest_invalid_service_type_password_auth(self, client: AuthClient):
        user_set = get_user_set("password_set_3")
        assert client.auth_password(user_set["eda"], "i am not a real service").status_code == 400
        assert client.auth_password(user_set["eda"], "controller").status_code == 400

    def subtest_invalid_auth_code(self, client: AuthClient):
        user = User.objects.get(username="user1")
        url = get_relative_url("legacy_auth-authenticate-sso")

        for k in client.service_routes:
            service = client.service_routes[k]
            auth_code = self._get_bogus_auth_code(
                user.username,
                service.service_cluster.service_id,
                user.resource.service_id,
            )
            assert client.client.get(url + "?auth_code=" + auth_code).status_code == 400

    def subtest_authenticators_are_created(self, client: AuthClient):
        services = client.service_routes
        kc_saml = "https://keycloak.example.com/auth/realms/saml/protocol/saml"
        shib_saml = "https://shibboleth.example.com/shib/idp"
        kc_oidc = "https://keycloak.example.com/auth/realms/oidc/protocol/openid-connect/auth"

        expected_authenticators = [
            {"type": "legacy_password", "service": services["awx"].service_cluster, "django_backend": None, "sso_server": None},
            {"type": "legacy_sso", "service": services["awx"].service_cluster, "django_backend": "oidc", "sso_server": kc_oidc},
            {"type": "legacy_sso", "service": services["awx"].service_cluster, "django_backend": "saml", "sso_server": shib_saml},
            {"type": "legacy_sso", "service": services["awx"].service_cluster, "django_backend": "saml", "sso_server": kc_saml},
            {"type": "legacy_password", "service": services["galaxy"].service_cluster, "django_backend": None, "sso_server": None},
            {"type": "legacy_sso", "service": services["galaxy"].service_cluster, "django_backend": "keycloak", "sso_server": kc_oidc},
            {"type": "legacy_password", "service": services["eda"].service_cluster, "django_backend": None, "sso_server": None},
        ]

        for auth in expected_authenticators:
            assert MigratedAuthenticatorMetadata.objects.filter(**auth).exists()

        assert len(expected_authenticators) == MigratedAuthenticatorMetadata.objects.all().count()

    def subtest_ldap_password_auth(self, client: AuthClient):
        user_set = get_user_set("ldap_set_1")
        assert client.auth_password(user_set["eda"], "eda").status_code == 200

    def subtest_disable_local_login_after_sso_merge(self, client: AuthClient):
        user_set = get_user_set("disable_login")

        assert client.auth_password(user_set["awx"], "controller").status_code == 200
        assert client.finalize().status_code == 200
        assert client.reset().status_code == 200

        # attempt login
        resp = client.auth_password(user_set["awx"], "controller")
        assert resp.status_code == 200
        assert resp.data["is_authenticated"] is True

        # set up SSO
        assert client.auth_sso(user_set["galaxy"], "galaxy").status_code == 200
        assert client.finalize().status_code == 200
        assert client.reset().status_code == 200

        # attempt to login with password
        assert client.auth_password(user_set["awx"], "controller").status_code == 400

    def subtest_disable_local_login_after_ldap_merge(self, client: AuthClient):
        user_set = get_user_set("disable_login_ext")

        assert client.auth_password(user_set["galaxy"], "hub").status_code == 200
        assert client.finalize().status_code == 200
        assert client.reset().status_code == 200

        # attempt login
        resp = client.auth_password(user_set["galaxy"], "hub")
        assert resp.status_code == 200
        assert resp.data["is_authenticated"] is True

        # set up LDAP
        assert client.auth_password(user_set["awx"], "controller").status_code == 200
        assert client.finalize().status_code == 200
        assert client.reset().status_code == 200

        # attempt to login with password
        resp = client.auth_password(user_set["galaxy"], "hub")
        assert resp.status_code == 400
        assert 'linked to an external account' in resp.data[0]

    def subtest_prevent_different_type_external(self, client: AuthClient):
        user_set = get_user_set("already_linked_ext")

        # Log in with LDAP
        assert client.auth_password(user_set["awx"], "controller").status_code == 200
        assert client.finalize().status_code == 200
        assert client.reset().status_code == 200

        # attempt login
        resp = client.auth_password(user_set["awx"], "controller")
        assert resp.status_code == 200
        assert resp.data["is_authenticated"] is True

        # Try to link Radius
        resp = client.auth_password(user_set["galaxy"], "hub")
        assert resp.status_code == 400
        assert 'share the same type' in resp.data[0]

    def subtest_fail_link_two_sso_accounts(self, client: AuthClient):
        for user_set in ("two_sso_oidc", "two_sso_saml_kc", "two_sso_saml_ext"):
            user_set = get_user_set(user_set)
            assert client.auth_sso(user_set["galaxy"], "galaxy").status_code == 200
            assert client.auth_sso(user_set["awx"], "awx").status_code == 400
            client.reset()

    def subtest_newly_created_account(self, client: AuthClient):
        # I can't actually create new accounts and have them reverse sync in the service
        # test app, so I'm doing the next best thing here by taking migrated accounts and
        # making them look like they're new

        for user in User.objects.filter(username__endswith="fake_new_user"):
            user.resource.service_id = service_id()
            user.resource.save()

            PatchedAllServiceClient().update_resource(
                str(user.resource.ansible_id),
                data=ResourceRequestBody(resource_data={"username": user.username}, service_id=str(service_id())),
                partial=True,
            )

            user.original_accounts.all().delete()
            user.authenticator_users.all().delete()

        user_set = get_user_set("fake_new_user")
        self._test_merge_multiple_accounts(client, user_set, ("awx", "galaxy", "eda"), user_set["awx"].username, False, expect_initial_auth=True)

    def _test_merge_multiple_accounts(
        self, client: AuthClient, user_set, order, expected_username, expect_rename, username_for="awx", expect_initial_auth=False
    ):
        first = order[0]
        authenticated_services = []

        for service in order:
            account = user_set[service]
            if account.backend is not None:
                data = client.auth_sso(user_set[service], service).data
            else:
                data = client.auth_password(user_set[service], DOWN_TO_UP[service]).data

            if service == first:
                self._assert_initial_auth(data, expected_username, service, expect_rename=expect_rename, expect_initial_auth=expect_initial_auth)

            authenticated_services.append(service)
            self._assert_linked_accounts(data, user_set, authenticated_services)

        self._assert_finalize(client, user_set[username_for].username, len(order))

    def _assert_finalize(self, client, expected_username, expected_num_linked, new_username=None):
        resp = client.finalize(new_username=new_username)
        assert resp.status_code == 200

        data = resp.data

        assert len(data["linked_accounts"]) == expected_num_linked
        assert data["needs_rename"] is False
        assert data["is_authenticated"] is True
        assert data["is_migrated"] is True

        self._assert_me_username(client, expected_username)

    def _assert_me_username(self, client, expected_username):
        resp = client.client.get(get_relative_url("me-list"))
        assert resp.status_code == 200
        assert resp.data["results"][0]["username"] == expected_username

    def _assert_initial_auth(self, data, expect_username, expect_type, expect_rename=True, expect_initial_auth=False):
        assert data["username"] == expect_username
        assert data["needs_rename"] is expect_rename
        assert data["is_authenticated"] is expect_initial_auth
        assert data["is_migrated"] is expect_initial_auth

    def _assert_linked_accounts(self, data, user_set, services):
        ready = data["linked_accounts"]
        assert len(ready) == len(services)

        for r in ready:
            s_type = UP_TO_DOWN[r["service_type"]]
            assert s_type in services
            assert r["original_username"] == user_set[s_type].username

    def _get_bogus_auth_code(self, username, service_id, ansible_id):
        payload = {
            "iss": str(service_id),
            "type": "auth_code",
            "username": username,
            "sub": str(ansible_id),
            "exp": datetime.now() + timedelta(seconds=15),
            "sso_uid": username,
            "sso_backend": None,
            "sso_server": None,
            "oidc_alt_key": None,
        }
        return jwt.encode(payload, "fake key", "HS256")
