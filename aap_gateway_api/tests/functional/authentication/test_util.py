import pytest

from aap_gateway_api.authentication.util import get_login_redirect_override, load_social_auth_settings


@pytest.mark.django_db
def test_load_social_auth_settings():
    settings = load_social_auth_settings()
    assert 'SOCIAL_AUTH_USERNAME_IS_FULL_EMAIL' in settings
    assert settings == {'SOCIAL_AUTH_USERNAME_IS_FULL_EMAIL': False}


@pytest.mark.django_db
def test_login_redirect_override_no_override():
    settings = get_login_redirect_override()
    assert settings == ''


@pytest.mark.django_db
def test_login_redirect_override_with_override(set_preference):
    url = "https://example.com"
    set_preference('local_login', "LOGIN_REDIRECT_OVERRIDE", url)
    settings = get_login_redirect_override()
    assert settings == url
