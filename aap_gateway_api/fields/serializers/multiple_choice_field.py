from rest_framework.serializers import MultipleChoiceField


class MultipleChoiceFieldWithoutEmptyEnum(MultipleChoiceField):
    """A MultipleChoiceField that produces a valid OpenAPI array type via drf-spectacular.

    Uses _spectacular_annotation to always return a nullable array of integers,
    preventing drf-spectacular from generating enums with mixed types
    (e.g. [1, '', None]) which happens when allow_blank and allow_null are
    combined with integer choice keys.
    """

    @property
    def _spectacular_annotation(self):
        """Override schema generation to produce a valid OpenAPI array type.

        Always returns a custom schema to prevent drf-spectacular from generating
        enums with mixed types (e.g. [1, '', None]) which happens when allow_blank
        and allow_null are combined with integer choice keys.
        """
        return {'field': {'type': 'array', 'items': {'type': 'integer'}, 'nullable': True}}
