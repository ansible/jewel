from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import exceptions
from rest_framework.metadata import SimpleMetadata
from rest_framework.request import clone_request

from aap_gateway_api.fields.serializers import JSONListField


class SettingsPreferenceMetadata(SimpleMetadata):
    """
    This custom metadata class is used to include the "default" field in the response
    """

    def __init__(self):
        super().__init__()
        # Add some additional type annotations for UI to use to select the correct form widgets
        self.label_lookup[JSONListField] = "list"

    def determine_actions(self, request, view):
        """
        For the settings view we return information to communicate what fields are
        available, and their data-type
        """
        actions = {}
        # We add 'GET' method below as our only change from the superclass
        for method in {'GET', 'PUT', 'POST'} & set(view.allowed_methods):
            view.request = clone_request(request, method)
            try:
                # Test global permissions
                if hasattr(view, 'check_permissions'):
                    view.check_permissions(view.request)
                # Test object permissions
                if method == 'PUT' and hasattr(view, 'get_object'):
                    view.get_object()
            except (exceptions.APIException, PermissionDenied, Http404):
                pass
            else:
                # If user has appropriate permissions for the view, include
                # appropriate metadata about the fields that should be supplied.
                serializer = view.get_serializer()
                actions[method] = self.get_serializer_info(serializer)
            finally:
                view.request = request

        return actions

    def get_field_info(self, field):
        """
        Include the default value of a preference in the OPTIONS response if available,
        but only for unencrypted preferences to prevent exposure of sensitive default values.
        """
        field_info = super().get_field_info(field)
        if hasattr(field, 'initial') and field.initial == ENCRYPTED_STRING:
            # this field may hold secrets in default value so we won't add the default field here
            return field_info

        field_info['default'] = getattr(field, 'default', None)
        return field_info
