from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from rest_framework.metadata import SimpleMetadata


class SettingsPreferenceMetadata(SimpleMetadata):
    """
    This custom metadata class is used to include the "default" field in the response
    """

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
