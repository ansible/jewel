import base64

import pytest
from ansible_base.authentication.challenge import ChallengeAwareAuthenticationMixin
from ansible_base.lib.utils.response import get_relative_url
from rest_framework.settings import api_settings


def test_default_authentication_classes_have_the_expected_resolution_order():
    """Keep the generated and Gateway-specific authentication precedence intentional."""
    resolved_classes = [f"{auth_class.__module__}.{auth_class.__name__}" for auth_class in api_settings.DEFAULT_AUTHENTICATION_CLASSES]
    expected_classes = [
        "aap_gateway_api.authentication.service_token_auth.ServiceTokenAuthentication",
        "ansible_base.authentication.bearer_authentication.BearerAuthentication",
        "aap_gateway_api.authentication.basic_auth.logged_basic_auth.LoggedBasicAuthentication",
        "ansible_base.authentication.session.SessionAuthentication",
    ]
    assert resolved_classes == expected_classes, (
        "If you've added a new authentication class, ensure it is in the correct logical order and the documentation has been updated."
    )


@pytest.mark.django_db
def test_explicit_basic_credentials_take_precedence_over_an_existing_session(user_api_client, user, admin_user, local_authenticator, preference_manager):
    """Explicit credentials must win over an ambient browser session."""
    assert user.username != admin_user.username
    basic_credentials = base64.b64encode(f"{admin_user.username}:password".encode()).decode()

    with preference_manager.set("proxy", "gateway_basic_auth_enabled", True):
        user_api_client.credentials(HTTP_AUTHORIZATION=f"Basic {basic_credentials}")
        response = user_api_client.get(get_relative_url("me-list"))

    assert response.status_code == 200
    assert response.data["results"][0]["username"] == admin_user.username


def test_default_authentication_classes_use_the_challenge_aware_mixin():
    """Ensure every configured authenticator can preserve the applicable DRF challenge."""
    non_compliant_classes = [
        f"{auth_class.__module__}.{auth_class.__name__}"
        for auth_class in api_settings.DEFAULT_AUTHENTICATION_CLASSES
        if not issubclass(auth_class, ChallengeAwareAuthenticationMixin)
    ]

    assert not non_compliant_classes, (
        "Every DEFAULT_AUTHENTICATION_CLASSES entry must inherit ChallengeAwareAuthenticationMixin. "
        "See the authentication challenge developer documentation before adding an authenticator: "
        f"{non_compliant_classes}"
    )
