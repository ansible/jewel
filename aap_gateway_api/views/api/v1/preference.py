import collections
import logging

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.lib.utils.views.permissions import IsSuperuserOrAuditor
from ansible_base.oauth2_provider.permissions import OAuth2ScopePermission
from cryptography.fernet import InvalidToken
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema, extend_schema_view
from dynamic_preferences.exceptions import NotFoundInRegistry
from dynamic_preferences.serializers import SerializationError
from rest_framework import status
from rest_framework.response import Response

from aap_gateway_api.models import Preference
from aap_gateway_api.preferences import gateway_preference_registry
from aap_gateway_api.preferences.metadata import SettingsPreferenceMetadata
from aap_gateway_api.serializers import SettingPreferenceSerializer, SettingSectionListSerializer, SettingSectionSerializer
from aap_gateway_api.utils import get_default_value_by_preference, get_preference_sections, get_preference_value_by_preference
from aap_gateway_api.views.api.v1.common import AnsibleBaseView, GatewayModelViewSet

logger = logging.getLogger('aap.gateway.views.api.v1.preference')


def format_err_message(category_slug, preference_name, err_detail):
    """
    Formats an error message for preferences that are either read-only, encrypted, or not found.
    """
    err_messages = {
        'read_only': _("Preference '%(preference_name)s' in category '%(category_slug)s' is read-only. Action was not performed."),
        'encrypted': _("Preference '%(preference_name)s' in category '%(category_slug)s' is encrypted. Action was not performed."),
        'not_found': _("Preference '%(preference_name)s' in category '%(category_slug)s' was not found. Action was not performed."),
    }

    if err_detail in err_messages:
        return err_messages[err_detail] % {"preference_name": preference_name, "category_slug": category_slug}
    return _("An unknown error occurred with preference '%(preference_name)s' in category '%(category_slug)s'.") % {
        "preference_name": preference_name,
        "category_slug": category_slug,
    }


class SettingSectionView(AnsibleBaseView):
    """
    A view class for managing and displaying a group of settings for a specific category.
    Endpoint: '/api/gateway/v1/settings/<category_slug>/'
    Parameters:
    - category_slug: The category of the setting (e.g., 'proxy', 'configuration').
    """

    permission_classes = [OAuth2ScopePermission, IsSuperuserOrAuditor]
    metadata_class = SettingsPreferenceMetadata
    allow_service_token = True

    def get_serializer(self, *args, **kwargs):
        if not hasattr(self, 'serializer'):
            return SettingSectionSerializer()
        return self.serializer

    def options(self, request, category_slug, format=None):
        self.serializer = SettingSectionSerializer(category_slug)
        return super().options(request, category_slug, format)

    @extend_schema(operation_id="settings_getter", extensions={'x-ai-description': "Get Gateway preferences for a category, or 'all' for all categories"})
    def get(self, request, category_slug, format=None):
        self.serializer = SettingSectionSerializer(category_slug)
        return Response(self.serializer.to_representation())

    @extend_schema(extensions={'x-ai-description': 'Update Gateway preferences within a category'})
    def put(self, request, category_slug, format=None):
        self.serializer = SettingSectionSerializer(category_slug)
        updated_data = self.serializer.validate_and_save(request.data)
        return Response(updated_data)

    @extend_schema(
        operation_id="settings_destroyer",
        extensions={'x-ai-description': 'Revert Gateway category preferences to defaults, excluding read-only and encrypted settings'},
    )
    def delete(self, request, category_slug=None, *args, **kwargs):
        """
        Revert all preferences in the current category to their default values
        except for read_only or encrypted settings
        """

        self.serializer = SettingSectionSerializer(category_slug)

        if self.serializer.category_slug in ["all", None]:
            # Handle revert all settings
            categories = get_preference_sections()
        else:
            categories = [category_slug]

        to_revert_data = {}
        unchanged_data = {}

        # Revert settings to their default values, don't revert read_only/ encrypted settings
        for category in categories:
            for preference in gateway_preference_registry.preferences(category):
                if preference.read_only or preference.encrypted:
                    # Determine the reason for not reverting
                    err_detail = 'read_only' if preference.read_only else 'encrypted'
                    logger.info(format_err_message(category_slug, preference.name, err_detail))
                    unchanged_data[preference.name] = _("%(err_detail)s") % {"err_detail": err_detail}
                    continue
                default_value = get_default_value_by_preference(preference, preference.encrypted)
                if get_preference_value_by_preference(preference, preference.encrypted) != default_value:
                    to_revert_data[preference.name] = default_value

        if to_revert_data:
            self.serializer.validate_and_save(to_revert_data)
            logger.info(f"Preferences: '{list(to_revert_data.keys())}' in category '{category_slug}' have been reverted to default values.")
        return Response({'unchanged': unchanged_data, 'reverted': to_revert_data}, status=status.HTTP_200_OK)


PreferenceSection = collections.namedtuple('PreferenceSection', ('url', 'name'))


# Hides default /{id}/ endpoint from api docs.
@extend_schema_view(
    retrieve=extend_schema(exclude=True),
    list=extend_schema(extensions={'x-ai-description': 'List setting categories grouping related Gateway configuration preferences'}),
)
class SettingSectionViewSet(GatewayModelViewSet):
    """
    A view class for managing and displaying all section of settings, with their urls and names
    Endpoint: '/api/gateway/v1/settings/'
    """

    model = Preference  # Not exactly, but needed for the view.
    serializer_class = SettingSectionListSerializer
    filter_backends = []
    name = _('Setting Categories')
    http_method_names = ['get', 'head']

    def get_queryset(self):
        setting_categories = []
        sections = get_preference_sections()
        sorted_sections = ['all']
        sorted_sections.extend(sorted(sections))
        for section in sorted_sections:
            url = get_relative_url('setting-section-list', kwargs={'category_slug': section})
            setting_categories.append(PreferenceSection(url, section))
        return setting_categories


class SettingPreferenceView(AnsibleBaseView):
    """
    A view class for managing and displaying a single setting information for a specified category.
    URL pattern: '/api/gateway/v1/settings/<category_slug>/<preference_name>/'
    Parameters:
    - category_slug: The category of the setting (e.g., 'proxy', 'configuration').
    - preference_name: The name of the specific setting (e.g., 'request_timeout', 'default_page_size').
    """

    permission_classes = [OAuth2ScopePermission, IsSuperuserOrAuditor]
    allow_service_token = True

    def get_serializer(self, *args, **kwargs):
        if not hasattr(self, 'serializer'):
            return SettingPreferenceSerializer()
        return self.serializer

    @extend_schema(extensions={'x-ai-description': 'Get a single Gateway preference by category and name'})
    def get(self, request, category_slug, preference_name, *args, **kwargs):
        if category_slug == 'all':
            message = _(
                "Individual preferences can only be accessed with a specific category."
                "Please include the appropriate category in the URL to which the preference '%(preference_name)s' belongs."
            ) % {"preference_name": preference_name}
            return Response({"detail": message}, status=status.HTTP_404_NOT_FOUND)

        try:
            preference = Preference.objects.get(section=category_slug, name=preference_name)
        except Preference.DoesNotExist:
            message = format_err_message(category_slug, preference_name, err_detail="not_found")
            return Response({"detail": message}, status=status.HTTP_404_NOT_FOUND)
        except (InvalidToken, SerializationError):
            logger.critical(
                "Preference '%s' in category '%s' has corrupt data and cannot be decrypted. "
                "Consider running 'gateway-manage rotate_secret_key' to re-encrypt preferences.",
                preference_name,
                category_slug,
                exc_info=True,
            )
            message = _(
                "Preference '%(preference_name)s' in category '%(category_slug)s' has corrupt or undecryptable data. "
                "An administrator must resolve this before the value can be read."
            ) % {"preference_name": preference_name, "category_slug": category_slug}
            return Response({"detail": message}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        serializer = SettingPreferenceSerializer(preference)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(extensions={'x-ai-description': 'Revert a single Gateway preference to default, excluding read-only and encrypted settings'})
    def delete(self, request, category_slug, preference_name, *args, **kwargs):
        """
        revert the setting `preference_name` in section `category_slug` to its default value.
        The `category_slug` parameter must be specified (i.e., cannot be 'all')
        because Preference only guarantees uniqueness for the tuple (section, preference_name).
        Therefore, thus can be multiple settings with the same name in different sections.
        """

        try:
            preference = gateway_preference_registry.get(preference_name, category_slug)
        except NotFoundInRegistry:
            message = format_err_message(category_slug, preference_name, err_detail="not_found")
            logger.info(message)
            return Response({"detail": message}, status=status.HTTP_404_NOT_FOUND)

        if preference.read_only or preference.encrypted:
            detail = 'read_only' if preference.read_only else 'encrypted'
            message = format_err_message(category_slug, preference_name, detail)
            logger.info(message)
            return Response(
                {"detail": message},
                status=status.HTTP_405_METHOD_NOT_ALLOWED,
            )

        default_value = get_default_value_by_preference(preference, preference.encrypted)

        setting_section_serializer = SettingSectionSerializer(category_slug)
        setting_section_serializer.validate_and_save({preference_name: default_value})
        message = _("Preference '%(preference_name)s' in category '%(category_slug)s' reverted to default value.") % {
            "preference_name": preference_name,
            "category_slug": category_slug,
        }

        return Response({"detail": message}, status=status.HTTP_200_OK)
