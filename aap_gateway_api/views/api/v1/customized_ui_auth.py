from ansible_base.authentication.models import Authenticator
from ansible_base.authentication.views.ui_auth import UIAuth, generate_ui_auth_data
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.response import Response

from aap_gateway_api.models import ServiceAPIRoute, ServiceCluster
from aap_gateway_api.utils.preferences import get_preference_value


def get_default_hostname_for_service(service_type_name):
    service_cluster = ServiceCluster.get_cluster_by_type(service_type=service_type_name)
    if service_cluster is None:
        return ""
    api = ServiceAPIRoute.objects.get(service_cluster=service_cluster.pk)
    proto = "https" if api.is_service_https else "http"
    if api.service_port in (443, 80):
        port = ""
    else:
        port = f":{api.service_port}"
    host = api.service_cluster.nodes.first()
    if not host:
        return ""

    return f"{proto}://{host.address}{port}"


@extend_schema(
    request=None,
    responses={
        "200": inline_serializer(
            "custom_ui_auth",
            fields={
                "passwords": serializers.ListField(
                    child=inline_serializer(
                        "custom_ui_auth_password",
                        fields={
                            "name": serializers.CharField(),
                        },
                    )
                ),
                "ssos": serializers.ListField(
                    child=inline_serializer(
                        "custom_ui_auth_ssos",
                        fields={
                            "name": serializers.CharField(),
                            "login_url": serializers.CharField(),
                            "type": serializers.CharField(),
                        },
                    ),
                ),
                "show_login_form": serializers.BooleanField(),
                "login_redirect_override": serializers.CharField(),
                "custom_login_info": serializers.CharField(),
                "custom_logo": serializers.CharField(),
                "managed_cloud_install": serializers.BooleanField(),
                "legacy_controller_sso_url": serializers.CharField(),
                "legacy_automation_hub_sso_url": serializers.CharField(),
                "legacy_auth_enabled": serializers.BooleanField(),
            },
        ),
    },
)
class CustomUIAuth(UIAuth):
    """
    Extend the UIAuth view from DAB to show legacy auth information
    """

    def get(self, request, format=None):
        response = generate_ui_auth_data()

        # Ideally we'd use the preference defaults for this, but there doesn't seem to
        # be a way to set a preference default from the database.
        controller_url = get_preference_value("legacy_sso", "CONTROLLER_SSO_URL")
        hub_url = get_preference_value("legacy_sso", "AUTOMATION_HUB_SSO_URL")

        if not controller_url:
            controller_url = get_default_hostname_for_service("controller")

        if not hub_url:
            hub_url = get_default_hostname_for_service("hub")

        response["legacy_controller_sso_url"] = controller_url
        response["legacy_automation_hub_sso_url"] = hub_url
        response["legacy_auth_enabled"] = Authenticator.objects.filter(category="legacy").exists()

        return Response(response)
