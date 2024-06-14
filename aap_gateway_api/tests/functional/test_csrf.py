import warnings
from importlib import import_module
from io import StringIO

import pytest
from ansible_base.activitystream.models.entry import Entry
from ansible_base.authentication.models import Authenticator
from ansible_base.rbac.models import RoleDefinition, RoleTeamAssignment, RoleUserAssignment
from ansible_base.resource_registry.models import Resource
from django.core.management import call_command
from django.middleware.csrf import _get_new_csrf_string as new_csrf_token
from django.urls import reverse
from django.urls.resolvers import RoutePattern
from rest_framework.test import APIClient

"""
    This file tests each endpoint in /api/gateway/v1/docs for unenforced csrf endpoints
    It does not test gateway services for csrf vulnerabilities.

    If these tests fail for any reason other than CSRF not enforcing, xfail this until it works.

    If this test is failing for the intended reason, and there is a good reason to exclude the
    endpoint causing the failure from the test, add the endpoint to the EXCLUDED_ENDPOINTS variable in this file.
"""

# Set this flag if you want to see blindspots in coverage.
# It will show every endpoint in /admin, which clutters test results.
DEBUG_WARNINGS = False

EXCLUDED_ENDPOINTS = set(["/api/gateway/v1/docs/", "/api/gateway/v1/docs/redoc", "/api/gateway/v1/docs/schema"])
CSRF_PROTECTED_METHODS = set(("DELETE", "POST", "PUT"))


# Will sometimes need the url route or its name to create a usable url
class Endpoint:
    # list of url patterns that map to gateway endpoints
    url_patterns = [
        RoutePattern("/api/gateway/v1/<str:field>/"),
        RoutePattern("/api/gateway/v1/<str:field>/<path:catchall>/"),
        RoutePattern("/api/gateway/v1/"),
        RoutePattern("/api/gateway/v1/<path:catchall>/"),
    ]

    def __init__(self, url, view_class_path, view_name, parse_converters=False):
        self.url = url
        self.pattern = RoutePattern(url)
        # Will set self.pattern_match
        self.pattern_match = self.set_matching_pattern()
        if view_name:
            self.view = view_name
        elif self.pattern_match:
            # Not all views tested have names, so view class needs to be programatically imported
            path_split = view_class_path.rsplit(".", 1)
            class_name = path_split[-1]
            module_path = path_split[0]
            module = import_module(module_path)
            self.view = getattr(module, class_name, None)
        else:
            self.view = None

        if parse_converters:
            self.reverse()

    # Serves two purposes, see if API should be tested by us, extract further information for parsing
    def set_matching_pattern(self):
        for pattern in Endpoint.url_patterns:
            match = pattern.match(self.url)
            if match:
                return match
        return None

    def reverse(self, field_map=dict()) -> str | None:
        "Generates url from name, filling arguments with valid test data identifiers"
        if self.pattern.converters:
            field_scope = self.pattern_match[2].get("field", "")
            kwargs = {}
            for key in self.pattern.converters:
                value = field_map.get(field_scope, dict()).get(key, None)
                # Return none if none of the converters can be resolved
                if not value:
                    if DEBUG_WARNINGS:
                        warnings.warn(f"DEBUG Excluding {self.url} - unassigned converter {key}")
                    return None
                kwargs[key] = value
            return reverse(self.view, kwargs=kwargs)
        else:
            return self.url


@pytest.fixture
def csrf_enforced_admin_api_client(admin_api_client):
    admin_api_client.handler.enforce_csrf_checks = True
    return admin_api_client


@pytest.fixture(scope="session")
def all_application_urls():
    with StringIO() as out:
        # Get all endpoints
        call_command("show_urls", "--no-color", stdout=out)
        # slicing to remove empty line
        show_urls_lines = out.getvalue().split("\n")[:-1]
        endpoints = []
        for line in show_urls_lines:
            line_split = line.split("\t")
            if len(line_split) == 3:
                view_name = line_split[2]
            else:
                view_name = None
            endpoint = Endpoint(line_split[0], line_split[1], view_name)
            if endpoint.pattern_match is not None:
                endpoints.append(endpoint)
            elif DEBUG_WARNINGS:
                warnings.warn(f"DEBUG Excluding {endpoint.url} - does not match any route pattern that is being tested")
        return endpoints


# Checks some preconditions for generalized testing for an endpoint, including allowed methods, presence of url parameters
# intended to be used in conjunction with filter() method to remove None elements
# returns a tuple of the url input and a set of CSRF sensitive HTTP methods, None if there are none
def filter_url(endpoint: Endpoint, client: APIClient, field_map) -> tuple[str, set[str]] | None:
    if endpoint.url not in EXCLUDED_ENDPOINTS:
        url = endpoint.reverse(field_map)
        if url:
            response = client.options(url)
            allow_header = response.headers.get("Allow")
            if allow_header:
                allowed_methods = set(allow_header.split(", "))
                if "GET" in allowed_methods:
                    csrf_allowed_methods = allowed_methods.intersection(CSRF_PROTECTED_METHODS)
                    if len(csrf_allowed_methods) > 0:
                        return (url, csrf_allowed_methods)
                elif DEBUG_WARNINGS:
                    warnings.warn(f"DEBUG Excluding {endpoint.url} - does not have a GET endpoint, a specialized test is needed for this endpoint")
            elif DEBUG_WARNINGS:
                warnings.warn(f"DEBUG Excluding {endpoint.url} - did not return Allow header, consider writing a specialized test")
    elif DEBUG_WARNINGS:
        warnings.warn(f"DEBUG Excluding {endpoint.url} - excluded from CSRF testing via exclusion list")
    # In the event any of these if conditions fail, return None so we can filter these out
    return None


@pytest.fixture
def field_map(
    admin_user,
    oauth2_admin_access_token,
    team,
    organization,
    http_port_factory,
    authenticator_map_factory,
    service_api_route_gateway,
    service_node_gateway,
    service_cluster_gateway,
    additional_route_gateway,
):
    authenticator = Authenticator.objects.first()
    role_definition = RoleDefinition.objects.first()
    service_key = service_cluster_gateway.generate_key()
    user_assignment = RoleUserAssignment.objects.create(role_definition=role_definition, user=admin_user)
    team_assignment = RoleTeamAssignment.objects.create(role_definition=role_definition, team=team)

    yield {
        "users": {
            "pk": admin_user.pk,
        },
        "tokens": {
            "pk": oauth2_admin_access_token.pk,
        },
        "teams": {
            "pk": team.pk,
        },
        "organizations": {"pk": organization.pk},
        "http_ports": {
            "pk": http_port_factory().pk,
        },
        "authenticators": {"pk": authenticator.pk},
        "authenticator_maps": {
            "pk": authenticator_map_factory(authenticator=authenticator).pk,
        },
        "applications": {"pk": oauth2_admin_access_token.application.pk},
        "activitystream": {"pk": Entry.objects.first().pk},
        "service-index": {
            "ansible_id": str(Resource.objects.first().ansible_id),
            "name": "shared.user",
        },
        "settings": {
            "category_slug": "all",
        },
        "services": {
            "pk": service_api_route_gateway.pk,
        },
        "service_nodes": {
            "pk": service_node_gateway.pk,
        },
        "service_keys": {
            "pk": service_key.pk,
        },
        "service_clusters": {
            "pk": service_cluster_gateway.pk,
        },
        "routes": {
            "pk": additional_route_gateway.pk,
        },
        "role_definitions": {"pk": role_definition.pk},
        "role_user_assignments": {"pk": user_assignment.pk},
        "role_team_assignments": {"pk": team_assignment.pk},
    }

    user_assignment.delete()
    team_assignment.delete()


# this should be higher than function scoped, but we are dependent on many function-scoped fixtures
@pytest.fixture
def gateway_endpoints(all_application_urls, admin_api_client, field_map) -> list[tuple[str, set[str]]]:
    endpoints = []
    for endpoint in all_application_urls:
        endpoint = filter_url(endpoint, admin_api_client, field_map=field_map)
        # Only add to list if its a valid endpoint
        if endpoint is not None:
            endpoints.append(endpoint)
    return endpoints


def _test_csrf_endpoint(url, request_function, csrf_enforced_admin_api_client: APIClient, change_csrf_form_token=False, change_csrf_cookie=False):
    response = csrf_enforced_admin_api_client.post(url)
    assert response.status_code == 403

    response = csrf_enforced_admin_api_client.get(url, headers={"accept": "text/html"})
    if response.status_code == 200:
        # Get CSRF form token
        csrf_form_token = response.context.get("csrf_token", None)
        assert csrf_form_token is not None
        # Get CSRF cookie
        csrf_cookie = csrf_enforced_admin_api_client.cookies.get("csrftoken", None)
        assert csrf_cookie is not None

        # Modify CSRF cookie
        if change_csrf_cookie:
            csrf_enforced_admin_api_client.cookies.load({"csrftoken": new_csrf_token()})
        if change_csrf_form_token:
            csrf_form_token = new_csrf_token()
        # Make request that CSRF mixin does not like
        response = request_function(csrf_enforced_admin_api_client, url, {"csrf_token": csrf_form_token})

        assert response.status_code == 403
    else:
        raise Exception(f"GET {url}: Unexpected status code {response.status_code}")


# Tests CSRF double-token mitigations dynamically for as many endpoints as possible where the mitigations are in place
@pytest.mark.django_db
@pytest.mark.parametrize(
    "change_csrf_form_token,change_csrf_cookie",
    [
        (True, True),
        (True, False),
        (False, True),
    ],
)
def test_csrf_endpoints(gateway_endpoints, csrf_enforced_admin_api_client: APIClient, change_csrf_form_token, change_csrf_cookie):
    for url, methods in gateway_endpoints:
        for method in methods:
            # Determine what method to use, easier to do this here instead of 3 indentations later
            match method:
                case "POST":
                    request_function = APIClient.post
                case "PUT":
                    request_function = APIClient.put
                case "DELETE":
                    request_function = APIClient.delete
                case _:
                    raise Exception(f"unknown CSRF-mitigated method: {method} for url {url}")
            _test_csrf_endpoint(
                url, request_function, csrf_enforced_admin_api_client, change_csrf_cookie=change_csrf_cookie, change_csrf_form_token=change_csrf_form_token
            )
