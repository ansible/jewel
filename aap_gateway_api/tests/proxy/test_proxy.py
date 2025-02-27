import time
from json import dumps
from os import linesep
from unittest import mock

import pytest
from rest_framework.authentication import SessionAuthentication

from aap_gateway_api.proxy.control_plane import ExternalAuth, _ExternalAuth, get_drf_request

csrf_cookie_string = "aAKwsypSuCpSmU4SMt7WrbGmvTBYfryg"
bad_csrf_form_token = "gJElunW0ICBSx1jtgk9HGMD6qzTRdQdM3ycFn1DgkXi0UWFjDKUts1Azq5jmCTcS"

request_body_multipart = f'''-----------------------------25667258076756890893396248524
Content-Disposition: form-data; name=\"csrfmiddlewaretoken\"

{bad_csrf_form_token}
-----------------------------25667258076756890893396248524
'''.replace(
    linesep, "\r\n"
)

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
        self, method="GET", host="localhost", path="/", header_diff={}, body="", query="", is_internal_route="f", service_type="gateway", auth_type="JWT"
    ):
        self.method = method
        self.host = host
        self.path = path
        self.raw_body = bytes(body, "utf-8")
        self.headers = request_headers.copy()
        self.headers.update(header_diff)
        self.query = query
        self.headers["CONTENT_LENGTH"] = str(len(self.raw_body))

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

    def test_check_bad_db(self, ext_auth):
        from django.db import DatabaseError

        request = Request()

        with mock.patch("django.db.connections.create_connection", side_effect=DatabaseError('DB_error')):
            response = ext_auth.Check(request, None)

        # assert permission denied
        assert response.status.code == 7

    def _sleeper(self, dbname):
        time.sleep(10)

    def test_check_db_timeout(self, ext_auth):
        request = Request()

        with mock.patch("django.db.connections.create_connection", side_effect=self._sleeper):
            response = ext_auth.Check(request, None)

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
