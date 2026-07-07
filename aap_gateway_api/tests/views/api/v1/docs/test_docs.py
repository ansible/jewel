from unittest import mock

import pytest
import yaml
from django.urls import get_resolver, reverse
from rest_framework.metadata import SimpleMetadata


# Ignores non-existent objects and returns full OPTIONS metadata anyway
def determine_actions(self, request, view):
    actions = {}
    for method in {'PUT', 'POST'} & set(view.allowed_methods):
        serializer = view.get_serializer()
        actions[method] = self.get_serializer_info(serializer)
    return actions


class ApiSpecs:
    def __init__(self, admin_api_client):
        self.api_endpoints = []
        self.api_schemas = {}
        self.openapi_endpoints = []
        self.openapi_schemas = {}
        self.load_openapi_schema(admin_api_client)
        self.load_api_schemas(admin_api_client)

    @mock.patch.object(SimpleMetadata, 'determine_actions', determine_actions)
    def load_api_schemas(self, admin_api_client):
        # extract endpoints from resolver
        endpoint_templates = set(v[0][0][0] for k, v in get_resolver().reverse_dict.items())
        # prepend /
        endpoint_templates = [f"/{self.get_url(x)}" for x in endpoint_templates]
        self.api_endpoints = self.remove_problematic_urls(endpoint_templates)
        for endpoint in self.api_endpoints:
            url = self.get_url(endpoint)
            self.api_schemas[url] = {}

            opts_resp = admin_api_client.options(url)

            # Load allowed actions and pre-populate schema action list
            allowed_actions = [action.strip() for action in opts_resp.headers['Allow'].split(',') if action.strip() not in ["HEAD", "OPTIONS"]]
            for action in allowed_actions:
                self.api_schemas[url][action.upper()] = {}

            if opts_resp.status_code == 405:
                # OPTIONS request not permitted
                if 'not allowed' not in str(opts_resp.content):
                    raise RuntimeError(f"Unexpected 405 error from OPTIONS request to {url}: {opts_resp.content}")
                continue
            elif opts_resp.status_code != 200:
                raise RuntimeError(f"Unable to load API schema for {endpoint}: {opts_resp.content}")
            if not opts_resp.content or opts_resp.headers["Content-Type"] not in ["application/json", "application/vnd.oai.openapi"]:
                # Blank or HTML content, can't do anything w/ that
                continue
            api_options = yaml.safe_load(opts_resp.content)  # yaml loads both json and openapi OK

            if api_options and "actions" in api_options:
                for action in api_options["actions"]:
                    self.api_schemas[url][action.upper()] = api_options["actions"][action]

    def load_openapi_schema(self, admin_api_client):
        # Load openapi schema from schema endpoint
        schema_url = reverse("schema")
        schema = admin_api_client.get(schema_url).data

        for endpoint in schema["paths"]:
            api_url = self.get_url(endpoint)
            self.openapi_endpoints.append(api_url)
            self.openapi_schemas[api_url] = {}
            for action in schema["paths"][endpoint]:
                doc_schema = schema["paths"][endpoint][action]
                self.openapi_schemas[api_url][action.upper()] = {}
                if "requestBody" in doc_schema:
                    # Get schema object ref (KeyError anyone?)
                    request_body = doc_schema["requestBody"]
                    if (
                        "content" in request_body
                        and "application/json" in request_body["content"]
                        and "schema" in request_body["content"]["application/json"]
                        and "$ref" in request_body["content"]["application/json"]["schema"]
                    ):
                        doc_schema_ref = request_body["content"]["application/json"]["schema"]["$ref"].split('/')[-1]
                        # Get schema object and store (uppercase action)
                        self.openapi_schemas[api_url][action.upper()] = schema["components"]["schemas"][doc_schema_ref]

                # TODO parse and store response objects and parameters

    def get_url(self, endpoint):
        # Create valid reversible links
        replacements = [
            ('/%(pk)s/', '/1/'),
            ('/{id}/', '/1/'),
            ('/%(category_slug)s/', '/all/'),
            ('/{category_slug}/', '/all/'),
            ('/%(preference_name)s/', '/custom_logo/'),
            ('/{preference_name}/', '/custom_logo/'),
            ('/%(ansible_id)s/', '/dbc9d85d-af4a-48bb-87a1-d6384f32f3af/'),
            ('/{ansible_id}/', '/dbc9d85d-af4a-48bb-87a1-d6384f32f3af/'),
            ('/%(name)s/', '/shared.user/'),
            ('/{name}/', '/shared.user/'),
            ('/%(model_name)s/', '/inventory/'),
            ('/{model_name}/', '/inventory/'),
            ('/%(actor_pk)s/', '/1/'),
            ('/{actor_pk}/', '/1/'),
            ('/%(user_ansible_id)s/', '/1/'),
            ('/{user_ansible_id}/', '/1/'),
        ]
        url = endpoint
        for rep in replacements:
            url = url.replace(rep[0], rep[1])
        return url

    def remove_problematic_urls(self, endpoints):
        # This removes various problematic endpoints from the check, see reasons below
        valid_endpoints = []

        for endpoint in endpoints:
            # Django reports /api/gateway/v1/settings/{pk}/ as an endpoint, but it's not, maybe fix that
            if 'settings' in endpoint and endpoint.endswith('1/'):
                continue
            # docs are self-referential and don't work (except for schema)
            if endpoint.endswith('docs/') or endpoint.endswith('redoc/'):
                continue
            # login just redirects to API root, can't use
            if 'login' in endpoint or 'logout' in endpoint:
                continue
            # /v1/authenticators/<saml>/metadata/ -> SAMLMetadataView in DAB
            # which is a non-api view and doesn't render any doc data.
            # TODO fix in DAB then remove this exception
            if 'authenticators' in endpoint and endpoint.endswith('metadata/'):
                continue
            # /o/<action>/ endpoints are based on django (not DRF) views and
            # provide no data for openapi.
            # TODO fix in DAB and remove this exception
            if '/o/' in endpoint and not endpoint.endswith('o/'):
                continue
            # /.well-known/ catch-all returns JSON 404 for unhandled paths,
            # not an API endpoint
            if '.well-known' in endpoint:
                continue
            # control plane endpoints intentionally hidden
            if 'discovery' in endpoint:
                continue
            # app_url detail intentionally hidden
            if 'app_url' in endpoint and endpoint.endswith('1/'):
                continue
            # workload identity tokens intentionally hidden
            if 'workload_identity_tokens' in endpoint:
                continue
            valid_endpoints.append(endpoint)
        return valid_endpoints


@pytest.fixture(autouse=True, scope='function')
def loaded_apis(admin_api_client):
    return ApiSpecs(admin_api_client)


def test_all_apis_present(loaded_apis):
    assert set(loaded_apis.openapi_endpoints) == set(loaded_apis.api_endpoints), "Mismatch in endpoints reported by application and docs"


def test_actions(loaded_apis):
    for endpoint in loaded_apis.openapi_schemas.keys():
        assert set(loaded_apis.openapi_schemas[endpoint].keys()) == set(loaded_apis.api_schemas[endpoint].keys()), f"Mismatch in actions for {endpoint}"


def test_request_objects(loaded_apis):
    # Compare openapi schema with options schema
    for endpoint in loaded_apis.openapi_endpoints:
        for action in loaded_apis.openapi_schemas[endpoint].keys():
            # Check params
            if loaded_apis.openapi_schemas[endpoint][action]:
                for pname, description in loaded_apis.openapi_schemas[endpoint][action]["properties"].items():
                    # Some workarounds
                    if pname == "instances":
                        # The associate/disassociate relationships instances do not
                        # show up in OPTIONS params, just in the description.
                        continue
                    if loaded_apis.api_schemas[endpoint][action] == {}:
                        # There are a couple of endpoints that publish POST
                        # but have no parameters documented, skip these
                        continue

                    api_schema = loaded_apis.api_schemas[endpoint][action]
                    assert pname in api_schema, f"Parameter missing {endpoint} - {pname} - {action} - {loaded_apis.api_schemas[endpoint][action]}"
                    param_schema = api_schema[pname]

                    validate_param(pname, description, endpoint, param_schema)


def validate_param(pname, description, api_url, param_schema):
    if "type" in description:
        assert compare_types(param_schema["type"], description["type"]), f"Type mismatch between openapi and options for {api_url} - {pname}"
    if "readOnly" in description:
        if pname == "content_type" and 'role_definitions' in api_url:
            # This does not match, but it's OK because the
            # serializer depends on action.  See DAB rbac/api/views.py.
            return
        if pname == "type" and 'authenticators' in api_url:
            # This does not match, but it's OK because the
            # authenticator type field has different read-only behavior between
            # OpenAPI schema and OPTIONS endpoint.
            return
        assert description["readOnly"] == param_schema["read_only"], f"Read only mismatch between openapi and options for {api_url} - {pname}"
    if "nullable" in description:
        assert description["nullable"] != param_schema["required"], f"Nullability mismatch between openapi and options for {api_url} - {pname}"


def compare_types(api_type, doc_type):
    match api_type:
        # Not great, but field can be lots of things
        case "field":
            # DRF many-related fields present as array type
            return doc_type in ["string", "object", "integer", "boolean", "array"]
        case "datetime" | "slug" | "url" | "email" | "choice":
            return doc_type in ["string"]
        case "list" | "multiple choice":
            return doc_type in ["array"]
        case "float":
            return doc_type in ["number"]
        case "nested object":
            return doc_type == "object"
    return doc_type == api_type
