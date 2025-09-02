from rest_framework.serializers import JSONField


# For type annotation in SettingsPreferenceMetadata class, which is needed for the UI to determine which widget to use for preferences
class JSONListField(JSONField):
    """A JSONField that represents a list/array type in OpenAPI schema.

    This field fixes the schema consistency issue where OpenAPI and DRF OPTIONS metadata
    disagreed on the type of list-based preferences like CSRF_TRUSTED_ORIGINS.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set spectacular annotation for OpenAPI schema generation
        self._spectacular_annotation = {'field': {'type': 'array', 'items': {'type': 'string'}}}

    @property
    def type_label(self):
        """Override the type label to be 'list' instead of 'json'."""
        return 'list'
