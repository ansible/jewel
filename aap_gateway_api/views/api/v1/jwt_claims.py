import logging

from ansible_base.rbac.claims import get_claims_hash, get_user_claims, get_user_claims_hashable_form
from ansible_base.resource_registry.views import ResourceAPIMixin
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status

from aap_gateway_api.models import User
from aap_gateway_api.views.api.v1.common import AnsibleBaseView

logger = logging.getLogger('aap.gateway.views.jwt_claims')


@extend_schema(
    methods=["GET"],
    request=None,
    responses={
        "200": OpenApiTypes.OBJECT,
        "404": OpenApiTypes.OBJECT,
    },
    description="Get JWT claims for a specific user by their Ansible ID. Accessible by service tokens or superusers.",
)
class JWTClaimsView(ResourceAPIMixin, AnsibleBaseView):
    custom_action_label = "retrieve"  # For permission checking

    def get(self, request, user_ansible_id):
        try:
            user = get_object_or_404(User, resource__ansible_id=user_ansible_id)

            claims = get_user_claims(user)

            # Generate the claims hash
            hashable_claims = get_user_claims_hashable_form(claims)
            claims_hash = get_claims_hash(hashable_claims)
            claims['claims_hash'] = claims_hash

            resource_api_actions = getattr(request.user, 'resource_api_actions', None)
            if resource_api_actions:
                claims['resource_api_actions'] = resource_api_actions

            return JsonResponse(claims, status=status.HTTP_200_OK)

        except Http404:
            logger.warning(f"Unable to get user claims for user with ansible_id {user_ansible_id}, User not found")
            return JsonResponse(
                {"error": _("User with ansible_id %(user_ansible_id)s not found") % {"user_ansible_id": user_ansible_id}}, status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.exception(f"Error generating JWT claims for user {user_ansible_id}: {e}")
            return JsonResponse({"error": _("Failed to generate JWT claims, see logs for details")}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
