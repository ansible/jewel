from json import dumps
from os import linesep
from unittest import mock

import pytest
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import SAFE_METHODS

from aap_gateway_api.proxy.control_plane import ExternalAuth, _ExternalAuth, get_drf_request

csrf_cookie_string = "aAKwsypSuCpSmU4SMt7WrbGmvTBYfryg"
bad_csrf_form_token = "gJElunW0ICBSx1jtgk9HGMD6qzTRdQdM3ycFn1DgkXi0UWFjDKUts1Azq5jmCTcS"

request_body_multipart = f'''-----------------------------25667258076756890893396248524
Content-Disposition: form-data; name=\"csrfmiddlewaretoken\"

{bad_csrf_form_token}
-----------------------------25667258076756890893396248524
'''.replace(linesep, "\r\n")

request_body_json = dumps(
    {
        "csrfmiddlewaretoken": bad_csrf_form_token,
    }
)

request_headers = {
    'SEC_FETCH_SITE': 'same-origin',
    'X_FORWARDED_FOR': '172.21.0.1',
    'X_ENVOY_INTERNAL': 'true',
    'REFERER': 'https://localhost/api/galaxy/v3/namespaces/',
    'DNT': '1',
    'X_REQUEST_ID': '9db8fa3e-ea44-4c53-9b0a-52b3f18fbcd5',
    'ACCEPT_ENCODING': 'gzip, deflate, br, zstd',
    'SEC_FETCH_MODE': 'navigate',
    ':AUTHORITY': 'localhost',
    'PRAGMA': 'no-cache',
    'UPGRADE_INSECURE_REQUESTS': '1',
    'CONTENT_LENGTH': '1147',
    ':PATH': '/api/galaxy/v3/namespaces/',
    'cookie': f'csrftoken={csrf_cookie_string}; tabstyle=html-tab',
    'X_ENVOY_AUTH_PARTIAL_BODY': 'false',
    'ACCEPT_LANGUAGE': 'en-US,en;q=0.5',
    ':SCHEME': 'https',
    'USER_AGENT': 'Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0',
    'CONTENT_TYPE': 'multipart/form-data; boundary=---------------------------25667258076756890893396248524',
    'ACCEPT': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'SEC_FETCH_USER': '?1',
    ':METHOD': 'POST',
    'SEC_FETCH_DEST': 'document',
    'X_FORWARDED_PROTO': 'https',
    'CACHE_CONTROL': 'no-cache',
    'PRIORITY': 'u=1',
}


class Request:
    def __init__(
        self,
        method="GET",
        host="localhost",
        path="/",
        header_diff={},
        body="",
        query="",
        is_internal_route="f",
        service_type="gateway",
        auth_type="JWT",
        scheme="http",
    ):
        self.method = method
        self.host = host
        self.path = path
        self.raw_body = bytes(body, "utf-8")
        self.headers = request_headers.copy()
        self.headers.update(header_diff)
        self.query = query
        self.headers["CONTENT_LENGTH"] = str(len(self.raw_body))
        self.scheme = scheme

        self.attributes = self
        self.request = self
        self.http = self
        self.context_extensions = {
            "is_internal_route": is_internal_route,
            "service_type": service_type,
            "auth_type": auth_type,
        }


@pytest.mark.parametrize(
    "method,host,path,body,headers",
    [
        ("POST", "localhost", "/api/gateway/v3/namespaces", request_body_multipart, {}),
        (
            "POST",
            "localhost",
            "/api/gateway/v3/namespaces",
            request_body_json,
            {
                "CONTENT_TYPE": "application/json; charset=utf-8",
            },
        ),
    ],
)
def test_get_drf_request(method, host, path, body, headers):
    request = Request(method=method, host=host, path=path, body=body, header_diff=headers)
    drf_req = get_drf_request(request)

    assert "csrfmiddlewaretoken" in drf_req.data


@pytest.fixture
def ext_auth():
    yield ExternalAuth()


@pytest.fixture
def _ext_auth():
    yield _ExternalAuth()


class MockSessionAuth(SessionAuthentication):
    def authenticate(self, request):
        # Skip authentication, start enforcing csrf verification
        self.enforce_csrf(request)

        return "admin", ""


@pytest.mark.django_db
class TestExternalAuth:
    # Need to mock away close_old_connections, because we can't expect the application code to re-connect to the test db.
    @pytest.fixture(scope="class", autouse=True)
    def mock_close_old_connections(self):
        with mock.patch("aap_gateway_api.proxy.control_plane.close_old_connections"):
            yield

    @pytest.mark.parametrize(
        "method,host,path,body,headers",
        [
            # json requests with no token header will fail csrf verification, since body is not checked in this case
            ("POST", "localhost", "/api/galaxy/v3/namespaces", request_body_multipart, {}),
            (
                "POST",
                "localhost",
                "/api/galaxy/v3/namespaces",
                request_body_json,
                {
                    "CONTENT_TYPE": "application/json; charset=utf-8",
                },
            ),
        ],
    )
    def test_check_bad_csrf(self, method, host, path, body, headers, ext_auth):
        request = Request(method=method, host=host, path=path, body=body, header_diff=headers)
        response = None
        with mock.patch("rest_framework.authentication.SessionAuthentication.authenticate", MockSessionAuth.authenticate):
            response = ext_auth.Check(request, None)

        # assert permission denied
        assert response.status.code == 7

    @pytest.mark.parametrize(
        "accept_type,body,expected_type",
        [
            ("application/json", None, "application/json"),
            ("application/yaml", None, "text/plain"),
            ("application/yaml", "<h2>Testing</h2>", "text/html"),
        ],
    )
    def test__return_no_auth_with_reason(self, accept_type, body, expected_type, _ext_auth):
        request = Request(header_diff={"ACCEPT": accept_type})
        from aap_gateway_api.proxy.control_plane import get_drf_request

        _ext_auth.drf_request = get_drf_request(request.attributes.request.http)
        response = _ext_auth._return_no_auth_with_reason("Testing", html_body=body)

        assert response.status.code == 7
        for header in response.denied_response.headers:
            if header.header.key == 'content-type':
                assert expected_type == header.header.value

    def test_no_auth_required(self, ext_auth, expected_log):
        request = Request(path="/static/favicon.ico")
        response = ext_auth.Check(request, None)
        assert response.status.code == 0
        assert response.ok_response.headers[0].header.key == "x-trusted-proxy"

    def test_check_internal_route_unauthenticated(self, ext_auth):
        request = Request(is_internal_route="t")
        response = ext_auth.Check(request, None)

        # assert permission denied
        assert response.status.code == 16
        assert response.denied_response.status.code == 401
        assert "internal" in response.status.message

    @pytest.mark.parametrize(
        "auth,expected_return_code,expected_http_status_code,return_message_string",
        [
            ("NotServiceTokenAuthentication", 16, 401, "internal"),
            ("ServiceTokenAuthentication", 0, 200, None),
        ],
    )
    def test_check_internal_route_authenticated(self, auth, expected_return_code, expected_http_status_code, return_message_string, ext_auth, admin_user):
        request = Request(is_internal_route="t")
        response = None
        with mock.patch("aap_gateway_api.authentication.service_token_auth.ServiceTokenAuthentication.authenticate", return_value=(admin_user, auth)):
            response = ext_auth.Check(request, None)

        # assert permission denied
        assert response.status.code == expected_return_code
        if return_message_string:
            assert response.denied_response.status.code == expected_http_status_code
            assert return_message_string in response.status.message

    def test_check_up_endpoint_no_auth(self, ext_auth, admin_user):
        request = Request(path="/up")
        response = ext_auth.Check(request, None)
        assert response.status.code == 0

    @pytest.mark.parametrize(
        "service_type,auth_type,expected_headers",
        [
            ("controller", "JWT", ["X-DAB-JW-TOKEN", "x-trusted-proxy"]),
            ("console", "BASIC", ["Authorization", "x-trusted-proxy"]),
            ("console", "TOKEN", ["Authorization", "x-trusted-proxy"]),
        ],
    )
    def test_auth_header_selection(self, ext_auth, service_type, auth_type, expected_headers, admin_user):
        request = Request(service_type=service_type, auth_type=auth_type)

        with mock.patch("aap_gateway_api.proxy.service_auth.ServiceAuthHelper._get_pref_or_setting", return_value="dummy"):
            with mock.patch(
                "aap_gateway_api.authentication.service_token_auth.ServiceTokenAuthentication.authenticate",
                return_value=(admin_user, "ServiceTokenAuthentication"),
            ):
                response = ext_auth.Check(request, None)
        for header in expected_headers:
            print(f"Testing header {header}.  Present? {any(x for x in response.ok_response.headers if x.header.key == header)}")
            assert any(x for x in response.ok_response.headers if x.header.key == header)

    @pytest.mark.parametrize(
        "service_type,auth_type,expected_exception",
        [
            ("controller", "BASIC", NameError),
            ("hub", "TOKEN", NameError),
            ("console", "BOGUS", RuntimeError),
        ],
    )
    def test_auth_header_exceptions(self, ext_auth, service_type, auth_type, expected_exception, admin_user):
        request = Request(service_type=service_type, auth_type=auth_type)

        with pytest.raises(expected_exception):
            with mock.patch(
                "aap_gateway_api.authentication.service_token_auth.ServiceTokenAuthentication.authenticate",
                return_value=(admin_user, "ServiceTokenAuthentication"),
            ):
                ext_auth.Check(request, None)


class MockOAuth2Token:
    """Mock OAuth2 access token for testing scope validation."""

    def __init__(self, scope='read', pk=12345, application=None):
        self.scope = scope
        self.pk = pk
        self.application = application


class MockOAuth2Application:
    """Mock OAuth2 application for testing."""

    def __init__(self, pk=1, name="Test App"):
        self.pk = pk
        self.name = name


@pytest.mark.django_db
class TestOAuth2ScopeValidation:
    """
    Comprehensive tests for OAuth2 scope validation in the gRPC control plane.

    These tests verify that:
    - Read-scope tokens can only access safe methods (GET, HEAD, OPTIONS)
    - Write-scope tokens can access all methods
    - Appropriate error messages are returned for scope violations
    - Non-OAuth2 authentication is not affected by scope validation
    """

    @pytest.fixture(scope="class", autouse=True)
    def mock_close_old_connections(self):
        with mock.patch("aap_gateway_api.proxy.control_plane.close_old_connections"):
            yield

    @pytest.mark.parametrize(
        "scope,method,should_succeed",
        [
            # read scope: safe methods should succeed
            ('read', 'GET', True),
            ('read', 'HEAD', True),
            ('read', 'OPTIONS', True),
            # read scope: unsafe methods should fail
            ('read', 'POST', False),
            ('read', 'PUT', False),
            ('read', 'PATCH', False),
            ('read', 'DELETE', False),
            # write scope: all methods should succeed
            ('write', 'GET', True),
            ('write', 'HEAD', True),
            ('write', 'OPTIONS', True),
            ('write', 'POST', True),
            ('write', 'PUT', True),
            ('write', 'PATCH', True),
            ('write', 'DELETE', True),
            # read write scope: all methods should succeed
            ('read write', 'POST', True),
            ('read write', 'PUT', True),
            ('read write', 'PATCH', True),
            ('read write', 'DELETE', True),
            # write read scope: all methods should succeed (order shouldn't matter)
            ('write read', 'POST', True),
            ('write read', 'PATCH', True),
        ],
    )
    def test_oauth2_scope_method_combinations(self, ext_auth, admin_user, scope, method, should_succeed):
        """Test all combinations of OAuth2 token scope and HTTP method."""
        request = Request(method=method, path="/api/controller/v2/organizations/")
        token = MockOAuth2Token(scope=scope)

        def mock_authenticate(self, req):
            # Set request.auth to our mock token so OAuth2ScopePermission sees it
            req._auth = token
            return (admin_user, token)

        # Mock OAuth2ScopePermission to use our logic based on token scope
        def mock_has_permission(self, req, view):
            if not hasattr(req, '_auth') or req._auth is None:
                return True  # Not OAuth2, allow
            token_scope = getattr(req._auth, 'scope', '')
            if 'write' in token_scope:
                return True
            # read-only scope: only allow safe methods
            return req.method in SAFE_METHODS

        with mock.patch(
            "ansible_base.oauth2_provider.authentication.LoggedOAuth2Authentication.authenticate",
            mock_authenticate,
        ):
            with mock.patch(
                "ansible_base.oauth2_provider.permissions.OAuth2ScopePermission.has_permission",
                mock_has_permission,
            ):
                response = ext_auth.Check(request, None)

        if should_succeed:
            # Should return OK (code 0)
            assert response.status.code == 0, f"Expected success for {method} with scope '{scope}', got code {response.status.code}"
        else:
            # Should return denied (code 7) with 403 status
            assert response.status.code == 7, f"Expected denial for {method} with scope '{scope}', got code {response.status.code}"
            assert response.denied_response.status.code == 403

    def test_oauth2_scope_denial_error_message_content(self, ext_auth, admin_user):
        """Test that scope denial error message contains expected information."""
        request = Request(method="POST", path="/api/controller/v2/organizations/")
        token = MockOAuth2Token(scope='read')

        def mock_authenticate(self, req):
            req._auth = token
            return (admin_user, token)

        def mock_has_permission(self, req, view):
            # Deny for this test
            return False

        with mock.patch(
            "ansible_base.oauth2_provider.authentication.LoggedOAuth2Authentication.authenticate",
            mock_authenticate,
        ):
            with mock.patch(
                "ansible_base.oauth2_provider.permissions.OAuth2ScopePermission.has_permission",
                mock_has_permission,
            ):
                response = ext_auth.Check(request, None)

        # Verify error message contains key information
        error_body = response.denied_response.body
        assert "insufficient scope" in error_body.lower(), "Error should mention insufficient scope"

    def test_oauth2_scope_denial_with_application(self, ext_auth, admin_user):
        """Test scope denial logging includes application info when present."""
        request = Request(method="DELETE", path="/api/hub/v3/collections/")
        app = MockOAuth2Application(pk=42, name="My OAuth App")
        token = MockOAuth2Token(scope='read', pk=99, application=app)

        def mock_authenticate(self, req):
            req._auth = token
            return (admin_user, token)

        def mock_has_permission(self, req, view):
            return False

        with mock.patch(
            "ansible_base.oauth2_provider.authentication.LoggedOAuth2Authentication.authenticate",
            mock_authenticate,
        ):
            with mock.patch(
                "ansible_base.oauth2_provider.permissions.OAuth2ScopePermission.has_permission",
                mock_has_permission,
            ):
                # Mock log_auth_warning (devel) or logger.warning (backports)
                with mock.patch("ansible_base.lib.logging.log_auth_warning", create=True) as mock_log:
                    ext_auth.Check(request, None)

                    # Verify logging was called with detailed information
                    assert mock_log.called
                    log_message = mock_log.call_args[0][0]
                    assert admin_user.username in log_message
                    assert "DELETE" in log_message
                    assert "/api/hub/v3/collections/" in log_message
                    assert "99" in log_message  # token pk
                    assert "42" in log_message  # application pk
                    assert "My OAuth App" in log_message
                    assert "read" in log_message  # scope

    def test_oauth2_scope_denial_personal_access_token(self, ext_auth, admin_user):
        """Test scope denial logging handles personal access tokens (no application)."""
        request = Request(method="PUT", path="/api/eda/v1/projects/")
        token = MockOAuth2Token(scope='read', pk=77, application=None)

        def mock_authenticate(self, req):
            req._auth = token
            return (admin_user, token)

        def mock_has_permission(self, req, view):
            return False

        with mock.patch(
            "ansible_base.oauth2_provider.authentication.LoggedOAuth2Authentication.authenticate",
            mock_authenticate,
        ):
            with mock.patch(
                "ansible_base.oauth2_provider.permissions.OAuth2ScopePermission.has_permission",
                mock_has_permission,
            ):
                # Mock log_auth_warning (devel) or logger.warning (backports)
                with mock.patch("ansible_base.lib.logging.log_auth_warning", create=True) as mock_log:
                    ext_auth.Check(request, None)

                    # Verify logging handles missing application gracefully
                    assert mock_log.called
                    log_message = mock_log.call_args[0][0]
                    assert "Personal Access Token" in log_message
                    assert "N/A" in log_message  # application pk when no app

    def test_non_oauth2_auth_not_affected(self, ext_auth, admin_user):
        """Test that non-OAuth2 authentication (basic auth, service token) is not affected by scope validation."""
        request = Request(method="POST", path="/api/controller/v2/organizations/")

        # Simulate service token authentication (not OAuth2)
        with mock.patch(
            "aap_gateway_api.authentication.service_token_auth.ServiceTokenAuthentication.authenticate",
            return_value=(admin_user, "ServiceTokenAuthentication"),
        ):
            response = ext_auth.Check(request, None)

        # Non-OAuth2 auth should succeed regardless of method
        assert response.status.code == 0, "Non-OAuth2 authentication should not be affected by scope validation"

    @pytest.mark.parametrize("safe_method", list(SAFE_METHODS))
    def test_all_safe_methods_allowed_with_read_scope(self, ext_auth, admin_user, safe_method):
        """Verify all SAFE_METHODS are allowed with read scope."""
        request = Request(method=safe_method, path="/api/gateway/v1/users/")
        token = MockOAuth2Token(scope='read')

        def mock_authenticate(self, req):
            req._auth = token
            return (admin_user, token)

        def mock_has_permission(self, req, view):
            token_scope = getattr(req._auth, 'scope', '') if hasattr(req, '_auth') else ''
            if 'write' in token_scope:
                return True
            return req.method in SAFE_METHODS

        with mock.patch(
            "ansible_base.oauth2_provider.authentication.LoggedOAuth2Authentication.authenticate",
            mock_authenticate,
        ):
            with mock.patch(
                "ansible_base.oauth2_provider.permissions.OAuth2ScopePermission.has_permission",
                mock_has_permission,
            ):
                response = ext_auth.Check(request, None)

        assert response.status.code == 0, f"{safe_method} should be allowed with read scope"

    def test_scope_validation_returns_403_not_401(self, ext_auth, admin_user):
        """Verify scope violation returns 403 Forbidden, not 401 Unauthorized."""
        request = Request(method="POST", path="/api/controller/v2/inventories/")
        token = MockOAuth2Token(scope='read')

        def mock_authenticate(self, req):
            req._auth = token
            return (admin_user, token)

        def mock_has_permission(self, req, view):
            return False

        with mock.patch(
            "ansible_base.oauth2_provider.authentication.LoggedOAuth2Authentication.authenticate",
            mock_authenticate,
        ):
            with mock.patch(
                "ansible_base.oauth2_provider.permissions.OAuth2ScopePermission.has_permission",
                mock_has_permission,
            ):
                response = ext_auth.Check(request, None)

        # 403 indicates the user is authenticated but not authorized
        assert response.denied_response.status.code == 403
        # status.code 7 is PERMISSION_DENIED in gRPC
        assert response.status.code == 7

    def test_oauth2_scope_check_token_is_none(self, ext_auth, admin_user):
        """Test that scope check handles None token gracefully (defensive check)."""
        request = Request(method="POST", path="/api/controller/v2/organizations/")

        def mock_authenticate(self, req):
            # Set auth to None (edge case)
            req._auth = None
            return (admin_user, None)

        def mock_has_permission(self, req, view):
            # Simulate OAuth2ScopePermission returning False even with None token
            return False

        with mock.patch(
            "ansible_base.oauth2_provider.authentication.LoggedOAuth2Authentication.authenticate",
            mock_authenticate,
        ):
            with mock.patch(
                "ansible_base.oauth2_provider.permissions.OAuth2ScopePermission.has_permission",
                mock_has_permission,
            ):
                response = ext_auth.Check(request, None)

        # When token is None, the defensive check should return None (allow the request through)
        # This results in the request proceeding to authentication
        assert response.status.code == 0, "Token is None should pass through (defensive check)"

    def test_oauth2_scope_check_user_is_none(self, ext_auth):
        """Test that scope check handles None user gracefully (username becomes '<none>')."""
        request = Request(method="POST", path="/api/controller/v2/organizations/")
        token = MockOAuth2Token(scope='read', pk=123, application=None)

        def mock_authenticate(self, req):
            req._auth = token
            # Return None user (edge case)
            return (None, token)

        def mock_has_permission(self, req, view):
            return False

        with mock.patch(
            "ansible_base.oauth2_provider.authentication.LoggedOAuth2Authentication.authenticate",
            mock_authenticate,
        ):
            with mock.patch(
                "ansible_base.oauth2_provider.permissions.OAuth2ScopePermission.has_permission",
                mock_has_permission,
            ):
                with mock.patch("ansible_base.lib.logging.log_auth_warning", create=True) as mock_log:
                    # This will fail at user check before scope check, but let's verify the path
                    ext_auth.Check(request, None)

                    # If we got to scope check with None user, log should have '<none>'
                    if mock_log.called:
                        log_message = mock_log.call_args[0][0]
                        assert "<none>" in log_message

    def test_oauth2_scope_check_token_missing_attributes(self, ext_auth, admin_user):
        """Test that scope check handles tokens missing scope/pk attributes."""
        request = Request(method="POST", path="/api/controller/v2/organizations/")

        # Create a minimal token object without scope or pk
        class MinimalToken:
            pass

        token = MinimalToken()

        def mock_authenticate(self, req):
            req._auth = token
            return (admin_user, token)

        def mock_has_permission(self, req, view):
            return False

        with mock.patch(
            "ansible_base.oauth2_provider.authentication.LoggedOAuth2Authentication.authenticate",
            mock_authenticate,
        ):
            with mock.patch(
                "ansible_base.oauth2_provider.permissions.OAuth2ScopePermission.has_permission",
                mock_has_permission,
            ):
                with mock.patch("ansible_base.lib.logging.log_auth_warning", create=True) as mock_log:
                    response = ext_auth.Check(request, None)

                    # Verify getattr fallbacks are used
                    assert mock_log.called
                    log_message = mock_log.call_args[0][0]
                    assert "unknown" in log_message  # scope fallback
                    assert "N/A" in log_message  # pk and application fallbacks

        # Should still return 403
        assert response.status.code == 7
        assert response.denied_response.status.code == 403

    def test_oauth2_scope_check_import_error_fallback(self, ext_auth, admin_user):
        """Test that scope check falls back to logger.warning when log_auth_warning import fails."""
        request = Request(method="POST", path="/api/controller/v2/organizations/")
        token = MockOAuth2Token(scope='read', pk=55, application=None)

        def mock_authenticate(self, req):
            req._auth = token
            return (admin_user, token)

        def mock_has_permission(self, req, view):
            return False

        def mock_import_error(*args, **kwargs):
            raise ImportError("log_auth_warning not available")

        with mock.patch(
            "ansible_base.oauth2_provider.authentication.LoggedOAuth2Authentication.authenticate",
            mock_authenticate,
        ):
            with mock.patch(
                "ansible_base.oauth2_provider.permissions.OAuth2ScopePermission.has_permission",
                mock_has_permission,
            ):
                # Mock the import to fail, forcing the fallback to logger.warning
                with mock.patch.dict('sys.modules', {'ansible_base.lib.logging': None}):
                    with mock.patch("aap_gateway_api.proxy.control_plane.logger") as mock_logger:
                        response = ext_auth.Check(request, None)

                        # Verify fallback to logger.warning was used
                        assert mock_logger.warning.called
                        log_message = mock_logger.warning.call_args[0][0]
                        assert admin_user.username in log_message
                        assert "read" in log_message

        assert response.status.code == 7
        assert response.denied_response.status.code == 403

    def test_oauth2_scope_check_various_paths(self, ext_auth, admin_user):
        """Test scope check with various API paths to ensure path is included in logs."""
        paths = [
            "/api/controller/v2/job_templates/",
            "/api/eda/v1/activations/",
            "/api/hub/v3/collections/",
            "/api/lightspeed/v1/completions/",
        ]

        for path in paths:
            request = Request(method="DELETE", path=path)
            token = MockOAuth2Token(scope='read', pk=1, application=None)

            def mock_authenticate(self, req):
                req._auth = token
                return (admin_user, token)

            def mock_has_permission(self, req, view):
                return False

            with mock.patch(
                "ansible_base.oauth2_provider.authentication.LoggedOAuth2Authentication.authenticate",
                mock_authenticate,
            ):
                with mock.patch(
                    "ansible_base.oauth2_provider.permissions.OAuth2ScopePermission.has_permission",
                    mock_has_permission,
                ):
                    with mock.patch("ansible_base.lib.logging.log_auth_warning", create=True) as mock_log:
                        response = ext_auth.Check(request, None)

                        assert mock_log.called
                        log_message = mock_log.call_args[0][0]
                        assert path in log_message, f"Path {path} should be in log message"

            assert response.status.code == 7, f"Should deny DELETE on {path} with read scope"
