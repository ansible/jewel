from ansible_base.authentication.challenge import ChallengeAwareAuthenticationMixin
from rest_framework.settings import api_settings


def test_default_authentication_classes_have_the_expected_resolution_order():
    """Keep the generated and Gateway-specific authentication precedence intentional."""
    resolved_classes = [f"{auth_class.__module__}.{auth_class.__name__}" for auth_class in api_settings.DEFAULT_AUTHENTICATION_CLASSES]
    expected_classes = [
        "ansible_base.authentication.bearer_authentication.BearerAuthentication",
        "ansible_base.authentication.session.SessionAuthentication",
        "aap_gateway_api.authentication.basic_auth.logged_basic_auth.LoggedBasicAuthentication",
        "aap_gateway_api.authentication.service_token_auth.ServiceTokenAuthentication",
    ]
    assert resolved_classes == expected_classes, (
        "If you've added a new authentication class, ensure it is in the correct logical order and the documentation has been updated."
    )


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
