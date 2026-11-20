import pytest
from django.test import override_settings
from rest_framework import serializers

from aap_gateway_api.serializers.mixins import HideDeprecatedFieldsSerializerMixin


class ExampleSerializer(HideDeprecatedFieldsSerializerMixin, serializers.Serializer):
    current = serializers.CharField()
    legacy = serializers.CharField()

    deprecated_fields = {'legacy': 'The legacy field is deprecated.'}


@pytest.mark.parametrize(
    'hide_deprecated_fields, expected',
    [
        (False, {'current': 'keep', 'legacy': 'drop'}),
        (True, {'current': 'keep'}),
    ],
)
def test_hide_deprecated_fields_setting(hide_deprecated_fields, expected):
    with override_settings(HIDE_V1_API_DEPRECATED_FIELDS=hide_deprecated_fields):
        assert ExampleSerializer({'current': 'keep', 'legacy': 'drop'}).data == expected
