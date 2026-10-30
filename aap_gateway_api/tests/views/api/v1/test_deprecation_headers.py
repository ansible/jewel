import pytest
from ansible_base.lib.utils.response import get_relative_url
from django.urls import reverse

# -- Helpers ------------------------------------------------------------------


def _get_schema(client):
    return client.get(reverse("schema")).data


def _assert_deprecated_headers(response, expected_detail=None):
    """Assert X-API-Deprecated headers are present with optional detail check."""
    assert response["X-API-Deprecated"] == "true"
    if expected_detail is not None:
        assert expected_detail in response["X-API-Deprecated-Detail"]


def _assert_no_deprecated_headers(response):
    assert "X-API-Deprecated" not in response


# -- Service Key deprecation headers -----------------------------------------


class TestServiceKeyDeprecationHeaders:
    def test_post_returns_deprecation_headers(self, admin_api_client):
        url = get_relative_url("service_key-list")
        response = admin_api_client.post(url)
        _assert_deprecated_headers(response, "POST method has been removed")

    @pytest.mark.parametrize("method", ["put", "patch"])
    def test_update_returns_deprecation_headers(self, admin_api_client, method, service_key_factory, service_cluster_eda):
        key = service_key_factory(service_cluster_eda)
        url = get_relative_url("service_key-detail", kwargs={"pk": key.pk})
        payload = {"name": key.name, "is_active": key.is_active}
        response = getattr(admin_api_client, method)(url, data=payload, format="json")
        _assert_deprecated_headers(response, "fields are deprecated for PUT/PATCH")

    def test_get_list_returns_deprecation_headers(self, admin_api_client):
        url = get_relative_url("service_key-list")
        response = admin_api_client.get(url)
        _assert_deprecated_headers(response)

    def test_get_detail_returns_deprecation_headers(self, admin_api_client, service_key_factory, service_cluster_eda):
        key = service_key_factory(service_cluster_eda)
        url = get_relative_url("service_key-detail", kwargs={"pk": key.pk})
        response = admin_api_client.get(url)
        _assert_deprecated_headers(response)


# -- User field deprecation headers ------------------------------------------


class TestUserFieldDeprecationHeaders:
    def test_deprecated_field_authenticator_uid_triggers_header(self, admin_api_client, admin_user, local_authenticator):
        url = get_relative_url("user-detail", kwargs={"pk": admin_user.pk})
        response = admin_api_client.patch(url, data={"authenticator_uid": "test"}, format="json")
        _assert_deprecated_headers(response, "authenticator_uid")

    def test_deprecated_field_authenticators_triggers_header(self, admin_api_client, admin_user, local_authenticator):
        url = get_relative_url("user-detail", kwargs={"pk": admin_user.pk})
        response = admin_api_client.patch(url, data={"authenticators": [local_authenticator.pk]}, format="json")
        _assert_deprecated_headers(response, "authenticators")

    def test_no_deprecated_header_without_deprecated_fields(self, admin_api_client, admin_user):
        url = get_relative_url("user-detail", kwargs={"pk": admin_user.pk})
        response = admin_api_client.patch(url, data={"first_name": "Updated"}, format="json")
        assert response.status_code == 200
        _assert_no_deprecated_headers(response)

    def test_get_does_not_trigger_field_deprecation(self, admin_api_client, admin_user):
        url = get_relative_url("user-detail", kwargs={"pk": admin_user.pk})
        response = admin_api_client.get(url)
        assert response.status_code == 200
        _assert_no_deprecated_headers(response)


# -- Deprecated related user endpoints ---------------------------------------


class TestDeprecatedRelatedUserEndpoints:
    @pytest.mark.parametrize(
        "url_name,parent_fixture",
        [
            ("organization-users-list", "organization"),
            ("organization-admins-list", "organization"),
            ("team-users-list", "team"),
            ("team-admins-list", "team"),
        ],
    )
    def test_related_user_endpoint_returns_deprecation_headers(self, admin_api_client, url_name, parent_fixture, organization_factory, team_factory):
        if parent_fixture == "organization":
            parent = organization_factory()
        else:
            org = organization_factory()
            parent = team_factory(organization=org)
        url = get_relative_url(url_name, kwargs={"pk": parent.pk})
        response = admin_api_client.get(url)
        assert response.status_code == 200
        _assert_deprecated_headers(response, "deprecated and will be removed")

    def test_user_teams_returns_deprecation_headers(self, admin_api_client, admin_user):
        url = get_relative_url("user-teams-list", kwargs={"pk": admin_user.pk})
        response = admin_api_client.get(url)
        assert response.status_code == 200
        _assert_deprecated_headers(response, "deprecated and will be removed")

    def test_user_organizations_returns_deprecation_headers(self, admin_api_client, admin_user):
        url = get_relative_url("user-organizations-list", kwargs={"pk": admin_user.pk})
        response = admin_api_client.get(url)
        assert response.status_code == 200
        _assert_deprecated_headers(response, "deprecated and will be removed")


# -- OpenAPI schema deprecation -----------------------------------------------


class TestOpenAPIDeprecationSchema:
    def test_service_key_operations_marked_deprecated(self, admin_api_client):
        schema = _get_schema(admin_api_client)
        list_path = get_relative_url("service_key-list")
        detail_path = f"{list_path}{{id}}/"

        assert schema["paths"][list_path]["post"]["deprecated"] is True
        assert schema["paths"][list_path]["get"]["deprecated"] is True
        for method in ("get", "put", "patch", "delete"):
            assert schema["paths"][detail_path][method]["deprecated"] is True

    def test_service_key_post_has_detail_extension(self, admin_api_client):
        schema = _get_schema(admin_api_client)
        list_path = get_relative_url("service_key-list")
        post_op = schema["paths"][list_path]["post"]
        assert "POST method has been removed" in post_op["x-api-deprecated-detail"]

    def test_service_key_put_has_detail_extension(self, admin_api_client):
        schema = _get_schema(admin_api_client)
        detail_path = f"{get_relative_url('service_key-list')}{{id}}/"
        put_op = schema["paths"][detail_path]["put"]
        assert "fields are deprecated for PUT/PATCH" in put_op["x-api-deprecated-detail"]

    def test_service_key_patch_has_detail_extension(self, admin_api_client):
        schema = _get_schema(admin_api_client)
        detail_path = f"{get_relative_url('service_key-list')}{{id}}/"
        patch_op = schema["paths"][detail_path]["patch"]
        assert "fields are deprecated for PUT/PATCH" in patch_op["x-api-deprecated-detail"]

    def test_deprecated_related_user_endpoints_marked_in_schema(self, admin_api_client):
        schema = _get_schema(admin_api_client)
        deprecated_path_fragments = [
            "/organizations/{id}/users/",
            "/organizations/{id}/admins/",
            "/teams/{id}/users/",
            "/teams/{id}/admins/",
            "/users/{id}/teams/",
            "/users/{id}/organizations/",
        ]
        for fragment in deprecated_path_fragments:
            matching = [p for p in schema["paths"] if fragment in p]
            assert matching, f"No path found containing {fragment}"
            for path in matching:
                for method, op in schema["paths"][path].items():
                    if isinstance(op, dict) and "operationId" in op:
                        assert op.get("deprecated") is True, f"{method.upper()} {path} should be deprecated"

    def test_user_deprecated_fields_have_detail_in_schema(self, admin_api_client):
        schema = _get_schema(admin_api_client)
        schemas = schema["components"]["schemas"]
        for component_name in ("User", "PatchedUser"):
            assert component_name in schemas, f"{component_name} not in schema components"
            properties = schemas[component_name]["properties"]
            for field_name in ("authenticators", "authenticator_uid"):
                prop = properties[field_name]
                assert prop["deprecated"] is True, f"{component_name}.{field_name} should be deprecated"
                assert "x-api-deprecated-detail" in prop, f"{component_name}.{field_name} should have x-api-deprecated-detail"

    def test_non_deprecated_endpoints_not_marked(self, admin_api_client):
        schema = _get_schema(admin_api_client)
        non_deprecated_paths = [
            (get_relative_url("user-list"), "get"),
            (get_relative_url("organization-list"), "get"),
            (get_relative_url("team-list"), "get"),
        ]
        for path, method in non_deprecated_paths:
            op = schema["paths"][path][method]
            assert op.get("deprecated") is not True, f"{method.upper()} {path} should NOT be deprecated"
