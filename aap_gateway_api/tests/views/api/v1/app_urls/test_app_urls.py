import pytest
from ansible_base.lib.utils.response import get_relative_url


@pytest.mark.parametrize(
    "client_fixture, expected_status",
    [
        ("admin_api_client", 200),
        ("user_api_client", 200),
        ("unauthenticated_api_client", 401),
    ],
)
def test_app_urls_access(request, client_fixture, expected_status):
    """
    Testing to ensure that getting the app_url list returns HTTP 200, for any authenticated user, unless you are unauthenticated
    """
    url = get_relative_url("app_url-list")
    api_client = request.getfixturevalue(client_fixture)
    response = api_client.get(url)
    assert response.status_code == expected_status


@pytest.mark.parametrize(
    "client_fixture, expected_status",
    [
        ("admin_api_client", 400),
        ("user_api_client", 400),
        ("unauthenticated_api_client", 401),
    ],
)
@pytest.mark.django_db
def test_app_urls_details_access(request, oauth2_application, client_fixture, expected_status):
    """
    Testing to ensure that getting the app_url detail returns HTTP 400, unless you are unauthenticated
    """

    the_oauth2_application = oauth2_application[0]
    url = get_relative_url("app_url-detail", kwargs={'pk': the_oauth2_application.pk})
    api_client = request.getfixturevalue(client_fixture)
    response = api_client.get(url)
    assert response.status_code == expected_status


@pytest.mark.parametrize(
    "client_fixture, expected_status",
    [
        ("admin_api_client", 400),
        ("user_api_client", 400),
        ("unauthenticated_api_client", 401),
    ],
)
def test_app_urls_details_access_bad_pk(request, client_fixture, expected_status):
    """
    Testing to ensure that getting the app_url detail returns HTTP 400, unless you are unauthenticated, even with a bad pk
    """

    url = get_relative_url("app_url-detail", kwargs={'pk': 314159})
    api_client = request.getfixturevalue(client_fixture)
    response = api_client.get(url)
    assert response.status_code == expected_status


@pytest.mark.parametrize(
    "client_fixture, endpoint_type, rest_action, expected_status, details_response",
    [
        ("admin_api_client", "detail", "post", 405, "Method \"POST\" not allowed."),
        ("admin_api_client", "detail", "put", 405, "Method \"PUT\" not allowed."),
        ("admin_api_client", "detail", "patch", 405, "Method \"PATCH\" not allowed."),
        ("admin_api_client", "detail", "delete", 405, "Method \"DELETE\" not allowed."),
        ("admin_api_client", "list", "post", 405, "Method \"POST\" not allowed."),
        ("admin_api_client", "list", "put", 405, "Method \"PUT\" not allowed."),
        ("admin_api_client", "list", "patch", 405, "Method \"PATCH\" not allowed."),
        ("admin_api_client", "list", "delete", 405, "Method \"DELETE\" not allowed."),
    ],
)
@pytest.mark.django_db
def test_app_urls_create_update_delete(request, client_fixture, rest_action, endpoint_type, expected_status, details_response, oauth2_application):
    """
    Test that we can not create, update or delete oauth2 applications from the app_urls details api endpoint.
    """
    the_oauth2_application = oauth2_application[0]
    client = request.getfixturevalue(client_fixture)
    url = None
    response = None
    data = {'name': 'Unit Testing', 'app_url': 'http://example.com/app_url_unit_testing'}

    if endpoint_type == "detail":
        url = get_relative_url(f"app_url-{endpoint_type}", args=[the_oauth2_application.pk])
    else:
        url = get_relative_url(f"app_url-{endpoint_type}")

    if rest_action == "post":
        response = client.post(url, data=data)
    elif rest_action == "put":
        response = client.put(url, data=data)
    elif rest_action == "patch":
        response = client.patch(url, data=data)
    elif rest_action == "delete":
        response = client.delete(url, data=data)

    assert response is not None and response.status_code == expected_status
    assert response.data is not None and 'detail' in response.data and details_response in response.data['detail']
