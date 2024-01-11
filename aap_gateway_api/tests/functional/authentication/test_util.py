import pytest

from aap_gateway_api.authentication.util import load_social_auth_settings


@pytest.mark.django_db
def test_load_social_auth_settings():
    settings = load_social_auth_settings()
    assert 'SOCIAL_AUTH_USERNAME_IS_FULL_EMAIL' in settings
    assert settings == {'SOCIAL_AUTH_USERNAME_IS_FULL_EMAIL': False}
