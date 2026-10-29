from rest_framework.settings import api_settings


def test_default_authentication_classes_have_the_expected_resolution_order():
    """Keep the explicit-first precedence intentional when classes are added or reordered."""
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
