from datetime import datetime, timedelta
from unittest.mock import patch

import jwt
import pytest
import requests
from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_class
from ansible_base.authentication.models import Authenticator, AuthenticatorUser
from ansible_base.authentication.utils.authentication import determine_username_from_uid_social, get_or_create_authenticator_user
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.resource_registry.models import service_id
from django.core.management import call_command
from rest_framework.test import APIClient

from aap_gateway_api.models import DefaultServiceType, MigratedAuthenticatorMetadata, User
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

SEP_CHAR = "_"


def get_social_pipeline_kwargs(uid, username, authenticator, **kwargs):
    return {
        "uid": uid,
        "details": {"username": username},
        "backend": get_authenticator_class(authenticator.type)(database_instance=authenticator),
        **kwargs,
    }


class AuthClient:
    def __init__(self, service_routes):
        self.client = APIClient()
        self.service_routes = service_routes

    def normal_login(self, username, password):
        url = get_relative_url("login")
        next_url = get_relative_url("me-list")
        data = {"username": username, "password": password, "next": next_url}
        response = self.client.post(url, data, follow=True)
        assert response.status_code == 200

    def auth_sso(self, account: Account, service):
        url = get_relative_url("legacy_auth-authenticate-sso")
        service_api = self.service_routes[service]

        resp = requests.get(
            f"http://localhost:{service_api.service_port}/sso/?username={account.username}&backend={account.backend.backend}",
            allow_redirects=False,
        )

        if "Location" not in resp.headers:
            raise RuntimeError(f'Response did not have location header, headers:\n{resp.headers}\nstatus_code:\n{resp.status_code}')

        # The gateway API isn't actually running on localhost so we'll intercept the redirect and handle it manually.
        redirect = resp.headers["Location"]
        auth_code = redirect.split("?auth_code=", maxsplit=1)[1]

        self.client.get(f"{url}?auth_code={auth_code}", follow=True)
        return self.current_state()

    def auth_password(self, account: Account, service_type):
        url = get_relative_url(f"legacy_auth-{service_type}-password")
        return self.client.post(
            url,
            data={
                "username": account.username,
                "password": account.password,
            },
            follow=True,
        )

    def finalize(self, new_username=None, new_password=None):
        url = get_relative_url("legacy_auth-finalize")
        data = {"new_username": new_username, "aap_password": new_password}
        if new_username is None:
            data.pop("new_username")
        if new_password is None:
            data.pop("aap_password")
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
    def patched_authenticator_all_resource_client(self):
        with patch("aap_gateway_api.authentication.authenticator_plugins.legacy_external_password.AllServicesClient", PatchedAllServiceClient) as client:
            yield client

    @pytest.fixture
    def services(
        self,
        service_api_route_controller,
        service_api_route_eda,
        service_api_route_hub,
        service_api_route_gateway,
        patched_resource_client,
        patched_legacy_auth_client,
        patched_utils_resource_client,
        patched_authenticator_all_resource_client,
        admin_user,
        local_authenticator,
        ldap_authenticator,
        keycloak_authenticator,
    ):
        hub_key = service_api_route_hub.service_cluster.generate_key()
        eda_key = service_api_route_eda.service_cluster.generate_key()
        controller_key = service_api_route_controller.service_cluster.generate_key()

        awx = launch_service(
            "awx",
            service_api_route_controller.service_port,
            "legacy_auth",
            secret_key=controller_key.secret,
            save_std=False,
            user_prefix=service_api_route_controller.api_slug,
        )
        galaxy = launch_service(
            "galaxy", service_api_route_hub.service_port, "legacy_auth", secret_key=hub_key.secret, save_std=False, user_prefix=service_api_route_hub.api_slug
        )
        eda = launch_service(
            "eda", service_api_route_eda.service_port, "legacy_auth", secret_key=eda_key.secret, save_std=False, user_prefix=service_api_route_eda.api_slug
        )

        cmd_kwargs = {"username": admin_user.username, "merge_teams": True, "merge_organizations": True}

        call_command("migrate_service_data", api_slug=service_api_route_controller.api_slug, **cmd_kwargs)
        call_command("migrate_service_data", api_slug=service_api_route_hub.api_slug, **cmd_kwargs)
        call_command("migrate_service_data", api_slug=service_api_route_eda.api_slug, **cmd_kwargs)

        yield (service_api_route_controller, service_api_route_eda, service_api_route_hub)

        awx.kill()
        galaxy.kill()
        eda.kill()

    @pytest.mark.django_db(transaction=True)
    def test_all_legacy_auth(
        self,
        services,
        subtests,
        local_authenticator,
        ldap_authenticator,
        keycloak_authenticator,
        admin_client,
        unauthenticated_api_client,
    ):
        """
        All of the tests in this class will be run through this test. While this is not proper form
        for pytest, there are two reasons to do it this way:

        1. The "services" fixture needs to spin up 3 lightweight instances of the service_test_app.
           This is somewhat expensive operation, and the fixture used here is intented to be used
           across multiple tests in order to fully mimic how the legacy auth endpoint will be used
           in production.
        2. We want to persist the state of the django DB across multiple test runs. This is to verify
           that we aren't creating any conflicts as users login and are migrated into the gateway.
        """
        awx_svc, eda_svc, galaxy_svc = services

        self.local_authenticator = local_authenticator
        self.ldap_authenticator = ldap_authenticator
        self.keycloak_authenticator = keycloak_authenticator
        self.admin_client = admin_client
        self.unauthenticated_api_client = unauthenticated_api_client

        service_routes = {
            "awx": awx_svc,
            "eda": eda_svc,
            "galaxy": galaxy_svc,
        }

        SINGLE_TEST = None
        # Use this to run a single test. Just make sure you comment it out before commiting
        # SINGLE_TEST = "subtest_manually_migrate_sso_user"

        for attr in dir(self):
            if attr.startswith("subtest"):
                if SINGLE_TEST and attr != SINGLE_TEST:
                    continue
                with subtests.test(msg=attr):
                    getattr(self, attr)(AuthClient(service_routes))

        self.controller_oidc_authenticator = Authenticator.objects.get(name__startswith="controller: legacy_sso-oidc")
        self.controller_saml_authenticator = Authenticator.objects.get(name__startswith="controller: legacy_sso-saml-https://keycloak")
        self.hub_keycloak_authenticator = Authenticator.objects.get(name__startswith="hub: legacy_sso-keycloak")
        self.legacy_eternal_auth = Authenticator.objects.get(name__startswith="gateway: legacy_external_password")
        self.hub_legacy_pass = Authenticator.objects.get(name__startswith="hub: legacy_password")
        self.controller_legacy_pass = Authenticator.objects.get(name__startswith="controller: legacy_password")

        # Auto migrate SSO
        self.controller_saml_authenticator.auto_migrate_users_to = keycloak_authenticator
        self.controller_saml_authenticator.save()
        self.controller_oidc_authenticator.auto_migrate_users_to = keycloak_authenticator
        self.controller_oidc_authenticator.save()
        self.hub_keycloak_authenticator.auto_migrate_users_to = keycloak_authenticator
        self.hub_keycloak_authenticator.save()

        # Auto migrate LDAP
        self.legacy_eternal_auth.auto_migrate_users_to = self.ldap_authenticator
        self.legacy_eternal_auth.save()
        self.hub_legacy_pass.auto_migrate_users_to = self.ldap_authenticator
        self.hub_legacy_pass.save()
        self.controller_legacy_pass.auto_migrate_users_to = self.ldap_authenticator
        self.controller_legacy_pass.save()

        # The day2_test subtests should run after the main tests. Here we will be configuring
        # auto account migration and then running some of the users from the previous test through
        # a series of additional tests that simulate logging in with a newly configure authenticator.

        for attr in dir(self):
            if attr.startswith("day2_test"):
                if SINGLE_TEST and attr != SINGLE_TEST:
                    continue
                with subtests.test(msg=attr):
                    getattr(self, attr)(AuthClient(service_routes))

        assert SINGLE_TEST is None

    # Things to test
    # - User that has logged in can login on new sso
    # - User that has not logged in can login with ldap sso
    # - User that has logged in can login with new ldap
    # - User that has not logged in can login with new ldap
    # - User with one legacy authenticator can log in
    # - User with no legacy authenticator can log in

    # How to verify?
    # - users in services are merged
    # - extra auth users are deleted
    # - extra gateway users are deleted
    # - teams are the same?

    def _test_auto_migrate_sso(self, uid, sub, username, ctrl_legacy=None):
        if ctrl_legacy is None:
            ctrl_legacy = self.controller_oidc_authenticator

        assert AuthenticatorUser.objects.filter(provider=self.hub_keycloak_authenticator, uid=uid).exists()
        assert AuthenticatorUser.objects.filter(provider=ctrl_legacy, uid=sub).exists()

        kwargs = get_social_pipeline_kwargs(uid=uid, username=username, authenticator=self.keycloak_authenticator, response={"sub": sub})

        username = determine_username_from_uid_social(**kwargs)["username"]

        assert username == username
        assert not AuthenticatorUser.objects.filter(provider=self.hub_keycloak_authenticator, uid=uid).exists()
        assert not AuthenticatorUser.objects.filter(provider=ctrl_legacy, uid=sub).exists()
        assert User.objects.filter(username=username).exists()

    def day2_test_login_new_migrated_account_sso(self, client: AuthClient):
        self._test_auto_migrate_sso(uid="two_sso1", username="two_sso1", sub="4b4614e7-7086-496a-a4d5-694206b3f844")

    def day2_test_login_new_non_migrated_account_sso(self, client: AuthClient):
        self._test_auto_migrate_sso(uid="two_sso_not_migrated", username="two_sso_not_migrated", sub="3f7c3239-7272-4116-afd4-36e545d6e1ff")

    def day2_test_login_new_migrated_account_ldap(self, client: AuthClient):
        uid = "ldap_user_set1"

        assert AuthenticatorUser.objects.filter(provider=self.legacy_eternal_auth, uid=uid).exists()

        local_user, auth_user, created = get_or_create_authenticator_user(
            uid=uid,
            authenticator=self.ldap_authenticator,
            user_details={},
            extra_data={},
        )

        assert local_user.username == uid
        assert not AuthenticatorUser.objects.filter(provider=self.legacy_eternal_auth, uid=uid).exists()

    def day2_test_login_new_non_migrated_account_ldap(self, client: AuthClient):
        uid = "unmigrated_ldap_user"

        assert AuthenticatorUser.objects.filter(provider=self.hub_legacy_pass, uid=uid).exists()
        assert AuthenticatorUser.objects.filter(provider=self.controller_legacy_pass, uid=uid).exists()

        local_user, auth_user, created = get_or_create_authenticator_user(
            uid=uid,
            authenticator=self.ldap_authenticator,
            user_details={},
            extra_data={},
        )

        assert local_user.username == uid
        assert not AuthenticatorUser.objects.filter(provider=self.hub_legacy_pass, uid=uid).exists()
        assert not AuthenticatorUser.objects.filter(provider=self.controller_legacy_pass, uid=uid).exists()

    def day2_test_login_sso_account_already_exists(self, client: AuthClient):
        uid = "two_sso2"
        u = User.objects.create(username=f"{uid}_random_string")
        AuthenticatorUser.objects.create(provider=self.keycloak_authenticator, uid=uid, user=u)
        self._test_auto_migrate_sso(
            uid="two_sso2",
            username=uid,
            sub=uid,
            ctrl_legacy=self.controller_saml_authenticator,
        )

        u.refresh_from_db()
        assert u.username == uid

    def day2_test_login_ldap_account_already_exists(self, client: AuthClient):
        uid = "ldap_user_set2"

        u = User.objects.create(username=f"{uid}_random_string")
        AuthenticatorUser.objects.create(provider=self.ldap_authenticator, uid=uid, user=u)

        assert AuthenticatorUser.objects.filter(provider=self.legacy_eternal_auth, uid=uid).exists()

        local_user, auth_user, created = get_or_create_authenticator_user(
            uid=uid,
            authenticator=self.ldap_authenticator,
            user_details={},
            extra_data={},
        )

        assert local_user.username == uid
        assert not AuthenticatorUser.objects.filter(provider=self.legacy_eternal_auth, uid=uid).exists()

        u.refresh_from_db()
        assert u.username == uid

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
        self._test_merge_multiple_accounts(client, user_set, ("awx", "galaxy", "eda"), user_set["awx"].username, False, expect_password=False)

    def subtest_merging_all_accounts_same_pass(self, client: AuthClient):
        user_set = get_user_set("password_set_2")
        self._test_merge_multiple_accounts(client, user_set, ("awx", "galaxy", "eda"), user_set["awx"].username, False, expect_password=True)

    def subtest_merging_all_accounts_galaxy_first(self, client: AuthClient):
        user_set = get_user_set("password_set_3")
        username = client.service_routes["galaxy"].api_slug + SEP_CHAR + user_set["galaxy"].username
        self._test_merge_multiple_accounts(client, user_set, ("galaxy", "awx", "eda"), username, True, expect_password=True)

    def subtest_merging_all_accounts_eda_first(self, client: AuthClient):
        user_set = get_user_set("password_set_4")
        username = client.service_routes["eda"].api_slug + SEP_CHAR + user_set["eda"].username
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
            expect_password=True,
        )

    def subtest_merging_all_accounts_conflict_all_eda_first(self, client: AuthClient):
        user_set = get_user_set("conflict_all1")
        username = client.service_routes["eda"].api_slug + SEP_CHAR + user_set["eda"].username
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
            expect_password=True,
        )

    def subtest_merging_all_accounts_conflict_all_hub_first(self, client: AuthClient):
        user_set = get_user_set("conflict_all2")
        username = client.service_routes["galaxy"].api_slug + SEP_CHAR + user_set["galaxy"].username
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

        self._test_merge_multiple_accounts(client, user_set_1, ("awx", "galaxy"), user_set_1["awx"].username, False, expect_password=True)

        # Check that we can't link another hub account
        response = client.auth_password(user_set_2["galaxy"], service_type="hub")
        assert response.status_code == 400

        # login with the EDA account
        resp = client.auth_password(user_set_3["eda"], "eda")
        assert resp.status_code == 200
        new_username = user_set_3["eda"].username + "renamed"

        # Check that account renaming works
        resp = client.finalize(new_username=new_username, new_password="pass")
        self._assert_me_username(client, new_username)

        client.reset()

        # login with our initial set of already migrated accounts to try and hook them up to the
        # new EDA account.
        client.normal_login(user_set_3["eda"].username + "renamed", "pass")
        resp = client.current_state()
        data = resp.data

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
            expect_password=True,
        )

    def subtest_fail_invalid_password(self, client: AuthClient):
        bad_password = Account(None, None, None, "bad password", username="user1")
        assert client.auth_password(bad_password, "controller").status_code == 400

        bad_username = Account(None, None, None, "pass", username="IDoNotExist")
        assert client.auth_password(bad_username, "controller").status_code == 400

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
            resp = client.client.get(url + "?auth_code=" + auth_code)
            assert "auth_failed" in resp.headers["Location"]

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
        assert client.finalize(new_password="pass").status_code == 200
        assert client.reset().status_code == 200

        # attempt login
        client.normal_login(user_set["awx"].username, user_set["awx"].password)

        # set up SSO
        assert client.auth_sso(user_set["galaxy"], "galaxy").status_code == 200
        assert client.finalize().status_code == 200
        assert client.reset().status_code == 200

        # attempt to login with password
        assert client.auth_password(user_set["awx"], "controller").status_code == 400

    def subtest_disable_local_login_after_ldap_merge(self, client: AuthClient):
        user_set = get_user_set("disable_login_ext")

        resp = client.auth_password(user_set["galaxy"], "hub")
        assert resp.status_code == 200
        assert resp.data["allow_rename"] is True
        assert client.finalize(new_password="pass").status_code == 200
        assert client.reset().status_code == 200

        self._assert_normal_login(user_set["galaxy"].username, "pass")

        # set up LDAP
        resp = client.auth_password(user_set["awx"], "controller")
        assert resp.status_code == 200
        assert resp.data["allow_rename"] is False
        assert client.finalize().status_code == 200
        assert client.reset().status_code == 200

        # attempt to login with password
        resp = client.auth_password(user_set["galaxy"], "hub")
        assert resp.status_code == 400
        assert 'account is not configured' in resp.data[0]

        self._assert_normal_login(user_set["awx"].username, user_set["awx"].password)

    def subtest_prevent_different_type_external(self, client: AuthClient):
        user_set = get_user_set("already_linked_ext")

        # Log in with LDAP
        assert client.auth_password(user_set["awx"], "controller").status_code == 200
        assert client.finalize().status_code == 200

        # attempt login
        self._assert_normal_login(user_set["awx"].username, user_set["awx"].password)

        # Try to link Radius
        resp = client.auth_password(user_set["galaxy"], "hub")
        assert resp.status_code == 400
        assert 'share the same type' in resp.data[0]

        self._assert_normal_login(user_set["awx"].username, user_set["awx"].password)

    def subtest_fail_link_two_sso_accounts(self, client: AuthClient):
        for user_set in ("two_sso_oidc", "two_sso_saml_kc", "two_sso_saml_ext"):
            user_set = get_user_set(user_set)
            assert len(client.auth_sso(user_set["galaxy"], "galaxy").data["linked_accounts"]) == 1
            assert len(client.auth_sso(user_set["awx"], "awx").data["linked_accounts"]) == 1
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

    def subtest_manually_migrate_password_user(self, client: AuthClient):
        user_set = get_user_set("manual_merge_password")
        auth_users = AuthenticatorUser.objects.filter(uid="manual_merge_password")
        assert auth_users.count() == 3

        # Manually merge user via the authenticator user API
        for ua in auth_users:
            url = get_relative_url("authenticator_user-move", kwargs={"pk": ua.pk})
            payload = {
                "new_authenticator": self.local_authenticator.id,
                "merge_accounts_with_same_uid": True,
            }
            response = self.admin_client.post(url, data=payload)
            assert response.status_code == 200

        # Check that old authenticator users are gone
        assert AuthenticatorUser.objects.filter(uid="manual_merge_password").count() == 1

        # Check that service id is updated
        user = User.objects.get(username="manual_merge_password")
        assert str(user.resource.service_id) == str(service_id())

        all_client = PatchedAllServiceClient()

        def _assert_exists(service, response):
            assert response.status_code == 200
            assert response.json()["resource_data"]["username"] == "manual_merge_password"

        # Check that the service ID has been updated in all the services
        all_client.with_callback(_assert_exists).get_resource(str(user.resource.ansible_id))

        user.set_password("new_pass")
        user.save()

        # Check that the user can login with the new password
        url = get_relative_url("login")
        next_url = get_relative_url("me-list")
        data = {"username": "manual_merge_password", "password": "new_pass", "next": next_url}
        response = self.unauthenticated_api_client.post(url, data, follow=True)
        assert response.status_code == 200
        assert response.data["results"][0]["username"] == "manual_merge_password"

        # Check that you can no longer login with legacy auth
        resp = client.auth_password(user_set["awx"], "controller")
        assert resp.status_code == 400

    def subtest_manually_migrate_sso_user(self, client: AuthClient):
        user_set = get_user_set("manual_merge_sso")
        auth_users = AuthenticatorUser.objects.filter(uid__in=["manual_merge_sso", "4c2213a6-7a88-4bf7-a43b-b8e553374cc3"])
        assert auth_users.count() == 2

        # Move first authenticator user
        first_user = auth_users[0].user
        url = get_relative_url("authenticator_user-move", kwargs={"pk": auth_users[0].pk})
        payload = {
            "new_authenticator": self.keycloak_authenticator.id,
            "merge_accounts_with_same_uid": False,
        }
        response = self.admin_client.post(url, data=payload)
        assert response.status_code == 200

        # Move second authenticator user
        url = get_relative_url("authenticator_user-move", kwargs={"pk": auth_users[1].pk})
        payload = {
            "new_authenticator": self.keycloak_authenticator.id,
            "merge_accounts_with_same_uid": False,
            "merge_with_user": first_user.pk,
            "new_uid": "manual_merge_sso",
        }
        response = self.admin_client.post(url, data=payload)
        assert response.status_code == 200

        # Check that old authenticator users are gone
        assert AuthenticatorUser.objects.filter(uid="manual_merge_sso").count() == 1

        # Check that service id is updated
        user = User.objects.get(username="manual_merge_sso")
        assert str(user.resource.service_id) == str(service_id())

        all_client = PatchedAllServiceClient()

        def _assert_exists(service, response):
            if service.service_cluster.service_type.name != DefaultServiceType.EDA:
                assert response.status_code == 200
                assert response.json()["resource_data"]["username"] == "manual_merge_sso"
            else:
                assert response.status_code == 404

        # Check that the service ID has been updated in all the services
        all_client.with_callback(_assert_exists).get_resource(str(user.resource.ansible_id))

        client.reset()

        # Check that you can no longer login with legacy auth
        resp = client.auth_sso(user_set["awx"], "awx")
        assert "is_authenticated" not in resp.data

    def subtest_ldap_login(self, client: AuthClient):
        user_set = get_user_set("ldap_user_set1")
        resp = client.auth_password(user_set["awx"], "controller")

        assert resp.status_code == 200
        self._assert_linked_accounts(resp.data, user_set, ["awx", "galaxy"])

        client.finalize()

        assert AuthenticatorUser.objects.filter(uid=user_set["awx"].username, provider__type__endswith="legacy_external_password").exists()

        self._assert_normal_login(user_set["awx"].username, user_set["awx"].password)

    def subtest_ldap_login_hub_first(self, client: AuthClient):
        user_set = get_user_set("ldap_user_set2")
        resp = client.auth_password(user_set["galaxy"], "hub")
        assert resp.status_code == 200
        self._assert_linked_accounts(resp.data, user_set, ["awx", "galaxy"])

        client.finalize()

        assert AuthenticatorUser.objects.filter(uid=user_set["galaxy"].username, provider__type__endswith="legacy_external_password").exists()

        self._assert_normal_login(user_set["galaxy"].username, user_set["galaxy"].password)

        url = get_relative_url("login")
        next_url = get_relative_url("me-list")
        data = {"username": user_set["galaxy"].username, "password": "wrong pass", "next": next_url}
        client = APIClient()
        assert client.post(url, data, follow=True).status_code == 401

    def _test_merge_multiple_accounts(
        self,
        client: AuthClient,
        user_set,
        order,
        expected_username,
        expect_rename,
        username_for="awx",
        expect_initial_auth=False,
        expect_password=False,
    ):
        first = order[0]
        authenticated_services = []

        last_service = None

        for service in order:
            account = user_set[service]
            if account.backend is not None:
                data = client.auth_sso(user_set[service], service).data
            else:
                data = client.auth_password(user_set[service], DOWN_TO_UP[service]).data

            last_service = data

            if service == first:
                self._assert_initial_auth(data, expected_username, service, expect_rename=expect_rename, expect_initial_auth=expect_initial_auth)

            authenticated_services.append(service)
            self._assert_linked_accounts(data, user_set, authenticated_services)

        assert last_service["needs_aap_password"] is expect_password

        new_pass = None
        if expect_password:
            new_pass = "password"

        self._assert_finalize(client, user_set[username_for].username, len(order), new_password=new_pass)

    def _assert_finalize(self, client, expected_username, expected_num_linked, new_username=None, new_password=None):
        resp = client.finalize(new_username=new_username, new_password=new_password)
        assert resp.status_code == 200

        data = resp.data

        assert len(data["linked_accounts"]) == expected_num_linked
        assert data["needs_rename"] is False
        assert data["is_authenticated"] is True
        assert data["is_migrated"] is True

        self._assert_me_username(client, expected_username)

        if new_password:
            self._assert_normal_login(expected_username, new_password)

    def _assert_me_username(self, client, expected_username):
        resp = client.client.get(get_relative_url("me-list"))
        assert resp.status_code == 200
        assert resp.data["results"][0]["username"] == expected_username

    def _assert_initial_auth(self, data, expect_username, expect_type, expect_rename=True, expect_initial_auth=False):
        assert isinstance(data, dict), f'Response was not a dictionary:\n{data}'

        assert data["username"] == expect_username
        assert data["needs_rename"] is expect_rename
        assert data["is_authenticated"] is expect_initial_auth
        assert data["is_migrated"] is expect_initial_auth

    def _assert_linked_accounts(self, data, user_set, services):
        assert isinstance(data, dict), f'Response was not a dictionary:\n{data}'

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

    def _assert_normal_login(self, username, password):
        url = get_relative_url("login")
        next_url = get_relative_url("me-list")
        data = {"username": username, "password": password, "next": next_url}

        client = APIClient()

        response = client.post(url, data, follow=True)
        assert response.status_code == 200
        assert response.data["results"][0]["username"] == username

    def test_finalize_rename_updates_local_uid(self, local_authenticator, user, user_api_client):
        au = AuthenticatorUser.objects.get(user=user, provider=local_authenticator)
        assert au.uid == user.username
        url = get_relative_url("legacy_auth-finalize")
        data = {"new_username": "definitely_not_user"}
        response = user_api_client.post(url, data=data)
        assert response.status_code == 200
        au.refresh_from_db()
        user.refresh_from_db()
        assert au.uid == user.username
