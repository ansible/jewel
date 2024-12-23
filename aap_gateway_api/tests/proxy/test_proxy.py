from json import dumps
from os import linesep
from unittest import mock

import pytest
from rest_framework.authentication import SessionAuthentication

from aap_gateway_api.proxy.control_plane import ExternalAuth, get_drf_request

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
    def __init__(self, method="GET", host="localhost", path="/", header_diff={}, body="", query=""):
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

        mock_cursor_item = mock.MagicMock()
        mock_cursor_item.execute.side_effect = DatabaseError('DB_error')
        mock_cursor = mock.MagicMock()
        mock_cursor.__enter__.return_value = mock_cursor_item

        with mock.patch("django.db.connection.cursor", return_value=mock_cursor):
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
    def test__return_no_auth_with_reason(self, accept_type, body, expected_type, ext_auth):
        request = Request(header_diff={"ACCEPT": accept_type})
        from aap_gateway_api.proxy.control_plane import get_drf_request

        ext_auth.drf_request = get_drf_request(request.attributes.request.http)
        response = ext_auth._return_no_auth_with_reason("Testing", html_body=body)

        assert response.status.code == 7
        for header in response.denied_response.headers:
            if header.header.key == 'content-type':
                assert expected_type == header.header.value
