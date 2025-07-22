import pytest
from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import RoleDefinition, RoleUserAssignment


@pytest.mark.parametrize(
    "client_fixture, expected_status",
    [
        ("admin_api_client", 200),
        ("user_api_client", 401),
    ],
)
def test_authenticator_user_list(request, client_fixture, expected_status, user, ldap_authenticator):
    AuthenticatorUser.objects.get_or_create(uid=user.username, user=user, provider=ldap_authenticator)
    client = request.getfixturevalue(client_fixture)
    url = get_relative_url("authenticator_user-list")
    response = client.get(url)
    assert response.status_code == expected_status
    if expected_status == 200:
        assert response.data["count"] == 2


def test_authenticator_user_list_readonly(admin_api_client, user, local_authenticator):
    url = get_relative_url("authenticator_user-list")
    would_be_payload = {
        "provider": local_authenticator.id,
        "user": user.id,
        "uid": user.username,
    }
    response = admin_api_client.post(url, data=would_be_payload)
    assert response.status_code == 405


def test_authenticator_user_detail(request, admin_api_client, user, local_authenticator):
    au, _ = AuthenticatorUser.objects.get_or_create(uid=user.username, user=user, provider=local_authenticator)
    url = get_relative_url("authenticator_user-detail", kwargs={"pk": au.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["user"] == user.id
    assert response.data["summary_fields"]["provider"]["id"] == local_authenticator.id


def test_authenticator_user_detail_readonly(admin_api_client, user, local_authenticator):
    au, _ = AuthenticatorUser.objects.get_or_create(uid=user.username, user=user, provider=local_authenticator)
    url = get_relative_url("authenticator_user-detail", kwargs={"pk": au.pk})
    would_be_payload = {
        "uid": "bananas",
    }
    response = admin_api_client.patch(url, data=would_be_payload)
    assert response.status_code == 405


def test_authenticator_user_move_only_post(admin_api_client, user, local_authenticator):
    ua, _ = AuthenticatorUser.objects.get_or_create(uid=user.username, user=user, provider=local_authenticator)
    url = get_relative_url("authenticator_user-move", kwargs={"pk": ua.pk})

    response = admin_api_client.get(url)
    assert response.status_code == 405

    response = admin_api_client.patch(url, data={})
    assert response.status_code == 405

    response = admin_api_client.put(url, data={})
    assert response.status_code == 405


def test_authenticator_user_move_mutually_exclusive_params(admin_api_client, user, random_user, local_authenticator, ldap_authenticator):
    ua, _ = AuthenticatorUser.objects.get_or_create(uid=user.username, user=user, provider=ldap_authenticator)
    url = get_relative_url("authenticator_user-move", kwargs={"pk": ua.pk})
    payload = {
        "new_authenticator": local_authenticator.id,
        "remove_other_authenticators": True,
        "keep_memberships": True,
        "merge_with_user": random_user.id,
        "merge_accounts_with_same_uid": True,
    }
    response = admin_api_client.post(url, data=payload)
    assert response.status_code == 400
    assert "mutually exclusive" in response.data['non_field_errors'][0]


def test_authenticator_user_move_happy_path_simple(admin_api_client, user, local_authenticator, ldap_authenticator):
    ua, _ = AuthenticatorUser.objects.get_or_create(uid=user.username, user=user, provider=ldap_authenticator)
    url = get_relative_url("authenticator_user-move", kwargs={"pk": ua.pk})
    payload = {
        "new_authenticator": local_authenticator.id,
        "remove_other_authenticators": True,
        "keep_memberships": True,
        "merge_with_user": "",
        "merge_accounts_with_same_uid": False,
    }
    response = admin_api_client.post(url, data=payload)
    assert response.status_code == 200
    assert response.data["summary_fields"]["provider"]["id"] == local_authenticator.id
    assert AuthenticatorUser.objects.filter(user=user, provider=local_authenticator).count() == 1
    assert AuthenticatorUser.objects.filter(user=user, provider=ldap_authenticator).count() == 0


@pytest.mark.parametrize(
    "remove_other_authenticators",
    [True, False],
)
def test_authenticator_user_move_keep_other_authenticators(
    admin_api_client, remove_other_authenticators, user, local_authenticator, ldap_authenticator, keycloak_authenticator
):
    AuthenticatorUser.objects.get_or_create(uid=user.username, user=user, provider=keycloak_authenticator)
    AuthenticatorUser.objects.get_or_create(uid="uh oh", user=user, provider=ldap_authenticator)
    ua, _ = AuthenticatorUser.objects.get_or_create(uid=user.username, user=user, provider=ldap_authenticator)
    url = get_relative_url("authenticator_user-move", kwargs={"pk": ua.pk})
    payload = {
        "new_authenticator": local_authenticator.id,
        "remove_other_authenticators": remove_other_authenticators,
        "keep_memberships": True,
        "merge_with_user": "",
        "merge_accounts_with_same_uid": False,
    }
    response = admin_api_client.post(url, data=payload)
    assert response.status_code == 200
    assert response.data["summary_fields"]["provider"]["id"] == local_authenticator.id
    assert AuthenticatorUser.objects.filter(user=user, provider=local_authenticator).count() == 1
    assert AuthenticatorUser.objects.filter(user=user, provider=ldap_authenticator).count() == (0 if remove_other_authenticators else 1)
    # Others (not from the old authenticator) should not be touched
    assert AuthenticatorUser.objects.filter(user=user, provider=keycloak_authenticator).count() == 1


@pytest.mark.parametrize(
    "keep_memberships",
    [True, False],
)
def test_authenticator_user_move_keep_memberships(
    admin_api_client,
    keep_memberships,
    user,
    local_authenticator,
    ldap_authenticator,
    organization,
):
    RoleUserAssignment.objects.create(object_id=organization.pk, role_definition=RoleDefinition.objects.get(name="Organization Member"), user=user)
    ua, _ = AuthenticatorUser.objects.get_or_create(uid=user.username, user=user, provider=ldap_authenticator)
    url = get_relative_url("authenticator_user-move", kwargs={"pk": ua.pk})
    payload = {
        "new_authenticator": local_authenticator.id,
        "remove_other_authenticators": True,
        "keep_memberships": keep_memberships,
        "merge_with_user": "",
        "merge_accounts_with_same_uid": False,
    }
    response = admin_api_client.post(url, data=payload)
    assert response.status_code == 200
    assert response.data["summary_fields"]["provider"]["id"] == local_authenticator.id
    assert AuthenticatorUser.objects.filter(user=user, provider=local_authenticator).count() == 1
    assert AuthenticatorUser.objects.filter(user=user, provider=ldap_authenticator).count() == 0
    assert RoleUserAssignment.objects.filter(user=user).count() == (1 if keep_memberships else 0)


def test_authenticator_user_move_merge_accounts_with_same_uid(admin_api_client, user, local_authenticator, ldap_authenticator, random_user):
    AuthenticatorUser.objects.get_or_create(uid=user.username, user=user, provider=local_authenticator)
    ua, _ = AuthenticatorUser.objects.get_or_create(uid=user.username, user=random_user, provider=ldap_authenticator)
    assert AuthenticatorUser.objects.filter(uid=user.username).count() == 2
    url = get_relative_url("authenticator_user-move", kwargs={"pk": ua.pk})
    payload = {
        "new_authenticator": local_authenticator.id,
        "remove_other_authenticators": True,
        "keep_memberships": True,
        "merge_accounts_with_same_uid": True,
    }
    response = admin_api_client.post(url, data=payload)
    assert response.status_code == 200
    assert response.data["summary_fields"]["provider"]["id"] == local_authenticator.id
    assert AuthenticatorUser.objects.filter(uid=user.username).count() == 1


def test_authenticator_user_move_merge_accounts_with_same_uid_but_same_user(admin_api_client, user, ldap_authenticator):
    ua, _ = AuthenticatorUser.objects.get_or_create(uid=user.username, user=user, provider=ldap_authenticator)
    assert AuthenticatorUser.objects.filter(uid=user.username).count() == 1
    url = get_relative_url("authenticator_user-move", kwargs={"pk": ua.pk})
    payload = {
        "new_authenticator": ldap_authenticator.pk,
        "remove_other_authenticators": True,
        "keep_memberships": True,
        "merge_accounts_with_same_uid": True,
    }
    response = admin_api_client.post(url, data=payload)
    assert "merge_accounts_with_same_uid" in response.data
    assert response.status_code == 400
    assert AuthenticatorUser.objects.filter(uid=user.username).count() == 1


def test_authenticator_user_merge_with_self(random_user, admin_api_client, user, local_authenticator, keycloak_authenticator):
    AuthenticatorUser.objects.get_or_create(uid=user.username, user=user, provider=local_authenticator)
    ua, _ = AuthenticatorUser.objects.get_or_create(uid=user.username, user=random_user, provider=keycloak_authenticator)

    url = get_relative_url("authenticator_user-move", kwargs={"pk": ua.pk})
    payload = {
        "new_authenticator": local_authenticator.id,
        "remove_other_authenticators": True,
        "keep_memberships": True,
        "merge_with_user": random_user.id,
        "merge_accounts_with_same_uid": False,
        "new_uid": "new_uid",
    }
    response = admin_api_client.post(url, data=payload)
    assert "merge_with_user" in response.data
    assert response.status_code == 400


def test_authenticator_user_move_new_uid(random_user, admin_api_client, user, local_authenticator, keycloak_authenticator):
    AuthenticatorUser.objects.get_or_create(uid=user.username, user=user, provider=local_authenticator)
    ua, _ = AuthenticatorUser.objects.get_or_create(uid=user.username, user=random_user, provider=keycloak_authenticator)

    url = get_relative_url("authenticator_user-move", kwargs={"pk": ua.pk})
    payload = {
        "new_authenticator": local_authenticator.id,
        "remove_other_authenticators": True,
        "keep_memberships": True,
        "merge_with_user": user.id,
        "merge_accounts_with_same_uid": False,
        "new_uid": "new_uid",
    }
    response = admin_api_client.post(url, data=payload)
    assert response.status_code == 200
    assert AuthenticatorUser.objects.filter(uid="new_uid").count() == 1


def test_authenticator_new_uid_after_merge(admin_api_client, user, local_authenticator, keycloak_authenticator, random_user):
    AuthenticatorUser.objects.get_or_create(uid=user.username, user=user, provider=local_authenticator)
    ua, _ = AuthenticatorUser.objects.get_or_create(uid=user.username, user=random_user, provider=keycloak_authenticator)
    assert AuthenticatorUser.objects.filter(uid=user.username).count() == 2
    url = get_relative_url("authenticator_user-move", kwargs={"pk": ua.pk})
    payload = {
        "new_authenticator": local_authenticator.id,
        "remove_other_authenticators": True,
        "keep_memberships": True,
        "merge_accounts_with_same_uid": True,
        "new_uid": "new_uid",
    }
    response = admin_api_client.post(url, data=payload)
    assert response.status_code == 200
    assert response.data["summary_fields"]["provider"]["id"] == local_authenticator.id
    user.refresh_from_db()
    assert AuthenticatorUser.objects.filter(uid=user.username).count() == 0
    assert AuthenticatorUser.objects.filter(uid="new_uid").count() == 1
