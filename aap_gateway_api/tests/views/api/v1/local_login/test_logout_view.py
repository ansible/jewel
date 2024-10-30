from unittest import mock

from ansible_base.lib.utils.response import get_relative_url


class TestLogoutView:
    allowed_host = 'www.example.com'

    def test_implicit_next(self, admin_api_client):
        url = get_relative_url('logout')
        response = admin_api_client.post(url)
        assert response.status_code == 302
        assert response.url == "/api/"

    def test_explicit_next_same_host(self, admin_api_client):
        url = get_relative_url('logout')
        response = admin_api_client.post(url + "?next=/next_page")
        assert response.status_code == 302
        assert response.url == "/next_page"

    def test_explicit_next_different_host_not_allowed(self, admin_api_client):
        url = get_relative_url('logout')
        response = admin_api_client.post(url + "?next=https://www.example.com/some/path")
        assert response.status_code == 302
        assert response.url == "/api/"

    # Following Red Hat Contributor's conclusion after also trying really hard.
    # See aap_gateway_api/tests/authentication/test_logged_basic_auth.py
    # The aap_gateway_api/views/api/v1/local_login.LoggedLogoutView has already been loaded and initialised.
    # ---------------------------------------------------------------------------------------------------
    # There is really no better way to do this. I tried. Really hard.
    # We can't use the 'settings' fixture here. Because even though DRF gets notified of the change,
    # the view already has the old settings as local variables. So we have to patch the view to fix that.
    # ---------------------------------------------------------------------------------------------------
    @mock.patch("aap_gateway_api.views.api.v1.local_login.LoggedLogoutView.success_url_allowed_hosts", [allowed_host])
    def test_explicit_next_different_host_allowed(self, admin_api_client):
        redirect_url = f'https://{TestLogoutView.allowed_host}/some/path'

        url = get_relative_url('logout')
        response = admin_api_client.post(url + f"?next={redirect_url}")
        assert response.status_code == 302
        assert response.url == redirect_url
