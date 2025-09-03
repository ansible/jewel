import logging

from ansible_base.lib.utils.response import get_relative_url
from django.core.exceptions import ValidationError
from django.urls import NoReverseMatch
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import APIException

from aap_gateway_api.models.migrate_data import MigrateServiceDataHasRan
from aap_gateway_api.utils.service_token import validate_service_token

logger = logging.getLogger('aap.gateway.authentication.service_token_auth')

service_token_header = "X-ANSIBLE-SERVICE-AUTH"


class MigrateDataNotCompleteError(APIException):
    """
    Exception raised when migration has not completed but service authentication is attempted.
    """

    status_code = 423
    default_detail = 'Service authentication is locked until migrate_service_data is complete.'
    default_code = 'migrate_service_data_not_complete'


class ServiceTokenAuthentication(BaseAuthentication):
    authorized_paths = [
        # Entries in this are a 3 item tuple where the items are (in order):
        #   1. The view name to do the reverse lookup on
        #   2. Any kwargs needed for for reverse (this can help limit views)
        #   3. An array of allowed methods
        ('setting-section-list', {'category_slug': 'analytics'}, ['get']),
        ('roleuserassignment-list', {}, ['get']),
        ('authenticator-list', {}, ['get', 'post', 'patch']),
        ('authenticatormap-list', {}, ['get', 'post', 'patch']),
        ('setting-section-list', {'category_slug': 'all'}, ['get', 'put']),
    ]

    def authenticate(self, request):
        token = request.headers.get(service_token_header, None)

        if token is None:
            return None

        # Check if migration has completed before allowing service authentication
        if not MigrateServiceDataHasRan.has_migration_completed():
            logger.info("Service authentication attempted but migrate_service_data has not completed.")
            raise MigrateDataNotCompleteError()

        try:
            token_data = validate_service_token(token)

            user = token_data["user"]
            service = token_data["service_cluster"]
            payload = token_data["token_data"]["payload"]

            if self.is_user_authorized(request, user, service, payload):
                logger.warning(f"User is authorized to access {request.path}.")
                return (user, 'ServiceTokenAuthentication')
            else:
                logger.warning(f"User not authorized to access {request.path}.")
                return None

        except ValidationError:
            logger.exception("Invalid token.")
            return None

    def is_user_authorized(self, request, user, service, token_data):
        resources_api = get_relative_url("service-index-root")

        # Allow services to authenticate to the resource registry, regardless of
        # whether or not they are authorized by the user to access the service.
        if request.path.startswith(resources_api):
            allowed_actions = [
                "list",
                "retrieve",
                "service-metadata",
                "manifest",  # resource type manifest like /v1/service-index/resource-types/shared.user/manifest/
                "create",
                "update",
                "destroy",
                "assign",
                "unassign",
            ]

            setattr(user, "resource_api_actions", allowed_actions)
            return True

        # Allow services to access JWT claims for any user
        # Note: This can't be added to authorized_paths because the authorized_paths mechanism
        # requires specific kwargs to generate URLs via get_relative_url() and we can't use
        # wildcards to accept any user slug in the URL pattern
        if request.path.startswith('/api/gateway/v1/jwt_claims/') and request.method.lower() == 'get':
            # Set the resource_api_actions based on what's in the token
            # This is used by the JWT claims view permission check
            # If no actions are set, default to allowing retrieve
            if not hasattr(user, 'resource_api_actions'):
                setattr(user, 'resource_api_actions', ['retrieve'])
            return True

        for path_info in self.authorized_paths:
            if len(path_info) != 3:
                logger.error(f"Invalid tuple in authorized_paths: {path_info}, it should have 3 components")
                continue

            view_name = path_info[0]
            kwargs = path_info[1]
            methods = path_info[2]

            try:
                url = get_relative_url(view_name, kwargs=kwargs)
            except NoReverseMatch:
                logger.warning(f"Unable to get relative url for {view_name}")
                continue

            if request.path.startswith(url) and request.method.lower() in [m.lower() for m in methods]:
                return True

        return False
