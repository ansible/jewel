from rest_framework.serializers import MultipleChoiceField


class MultipleChoiceFieldWithoutEmptyEnum(MultipleChoiceField):
    """A MultipleChoiceField that prevents drf-spectacular from generating empty enums.

    When a MultipleChoiceField has empty choices (e.g., when no Authenticators exist
    in the database during schema generation), drf-spectacular generates an invalid
    OpenAPI schema component with an empty enum. This field uses _spectacular_annotation
    to tell drf-spectacular to generate a simple array type instead of an enum when
    choices are empty.
    """

    @property
    def _spectacular_annotation(self):
        """Override schema generation to avoid empty enums.

        When choices are empty, returns a custom schema to prevent empty enum generation.
        When choices exist, returns an empty dict to let drf-spectacular use its default
        behavior (generating an enum with the available choices).

        Note: When choices are empty, we default to 'string' type since DRF's
        MultipleChoiceField serializes values as strings in JSON regardless of the
        Python type of the choice values.
        """
        choices = getattr(self, 'choices', [])
        if not choices:
            # Override: return array type to prevent empty enum generation
            # Use 'string' as default since DRF serializes MultipleChoiceField values
            # as strings in JSON, regardless of the Python type of choice values
            return {'field': {'type': 'array', 'items': {'type': 'string'}}}
        # No override: return empty dict to let drf-spectacular use default enum generation
        return {}
