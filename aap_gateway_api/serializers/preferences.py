import logging
from typing import Any, Optional

from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from dynamic_preferences import types
from dynamic_preferences.serializers import SerializationError
from rest_framework import serializers

from aap_gateway_api.models.preference import Preference
from aap_gateway_api.preferences import gateway_preference_registry
from aap_gateway_api.preferences.types import PEMPrivateKeyPreference
from aap_gateway_api.utils import (
    PREFERENCE_TYPE_CLASS_TO_SERIALIZER_FIELD_MAPPING,
    get_preference_value_by_preference,
    is_read_only_preference,
    update_preference_value,
)

logger = logging.getLogger('aap.gateway.serializers.preferences')


class SettingSectionListSerializer(serializers.Serializer):
    # This is the serializer for the list of categories (/api/gateway/v1/settings)
    """Serialize list of settings category"""

    url = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)


class SettingSectionSerializer(serializers.Serializer):
    # This is the serializer for a given category (like /api/gateway/v1/settings/all)
    def __init__(self, category_slug=None, *args, **kwargs):
        if category_slug == 'all':
            self.category_slug = None
        else:
            self.category_slug = category_slug
        super().__init__(None, *args, **kwargs)

    def get_fields(self) -> dict:
        long_string_fields = (
            types.LongStringPreference,
            PEMPrivateKeyPreference,
        )
        fields = super().get_fields()
        for registered_preference in gateway_preference_registry.preferences(self.category_slug):
            constructor = PREFERENCE_TYPE_CLASS_TO_SERIALIZER_FIELD_MAPPING.get(registered_preference.field_type, serializers.Field)
            read_only, _ = is_read_only_preference(registered_preference)

            fields[registered_preference.name] = constructor(
                initial=get_preference_value_by_preference(registered_preference),
                help_text=registered_preference.help_text,
                # No option being passed through the category is required because we might only be updating one.
                required=False,
                default=registered_preference.default,
                style={"base_template": "textarea.html"} if registered_preference.field_type in long_string_fields else None,
                read_only=read_only,
            )
            for field_name in ['max_value', 'min_value', 'label']:
                if hasattr(registered_preference, field_name):
                    setattr(fields[registered_preference.name], field_name, getattr(registered_preference, field_name))

        return fields

    def to_representation(self) -> dict:
        # Here value is the object from the views "get_object" method
        return_data = {}
        # Here we are going to loop over all of the registered preferences and get the value from the object the view created
        for registered_preference in gateway_preference_registry.preferences(self.category_slug):
            return_data[registered_preference.name] = get_preference_value_by_preference(registered_preference)

        return return_data

    def _serialize_and_validate_preference_value(self, registered_preference: object, new_value: Any) -> tuple[bool, Any, Optional[str]]:
        """
        This method converts the raw input `new_value` into a python type using its associated preference's serializer, and
        performs validation on the converted value

        Returns:
        - bool: True if the validation succeeds
        - parsed_value: The converted and validated value, None otherwise
        - e: Error messages, which is str or None
        """
        try:
            # First, convert the raw input to appropriate python
            # For boolean fields, to_python() expects a string, so we convert the input accordingly.
            # If the conversion fails, to_python() will raise a ValidationError.
            # we pass in str(new_value), replacing ' with " as a workaround for JSONPreferences because json.loads fails if the JSON string does not use
            # double quotes, no idea why.
            converter_arg = str(new_value).replace("'", '"') if new_value is not None else None
            converted_value = registered_preference.serializer.to_python(converter_arg)

            # Second, perform a usual validation
            registered_preference.validate(converted_value)

            # Then, catch the scenarios where the above missed
            if issubclass(registered_preference.__class__, types.IntegerPreference):
                if not isinstance(converted_value, int):
                    raise SerializationError("Must be an integer")
            if issubclass(registered_preference.__class__, types.StringPreference):
                if not isinstance(converted_value, str):
                    raise SerializationError("Must be a string")
            # if succeeds
            return True, converted_value, None
        except (SerializationError, serializers.ValidationError, ValidationError) as e:
            if isinstance(e, ValidationError):
                e = ', '.join(e.messages)
            return False, None, str(e)

    def process_fields(self, data: dict) -> tuple[dict, dict, dict]:
        validated_fields = {}
        errors = {}
        values_to_save = {}
        for registered_preference in gateway_preference_registry.preferences(self.category_slug):
            current_value = get_preference_value_by_preference(registered_preference, encrypted=True)
            validated_fields[registered_preference.name] = current_value

            if registered_preference.name not in data:
                # We were not passed this variable so we can skip it
                continue
            new_value = data[registered_preference.name]

            # If there is no change to the current preference setting value, skip
            if current_value == new_value:
                continue
            # Else, we are doing an update
            # Now, check for read only setting
            is_read_only, err_msg = is_read_only_preference(registered_preference)
            if is_read_only:
                errors[registered_preference.name] = err_msg
                continue

            # Next, check for values that should be encrypted
            if new_value != ENCRYPTED_STRING:
                masked_value = new_value
                if registered_preference.encrypted:
                    masked_value = ENCRYPTED_STRING
                logger.debug(f"Validating value change from {current_value} to {masked_value} for {registered_preference.name}")

                is_valid, parsed_value, err_msg = self._serialize_and_validate_preference_value(registered_preference, new_value)

                if not is_valid:
                    errors[registered_preference.name] = err_msg
                    continue

                # validation succeeded, we need to mark the setting to be saved
                values_to_save[registered_preference.name] = {'value': parsed_value, 'section': registered_preference.section.name}
                validated_fields[registered_preference.name] = masked_value

        return validated_fields, errors, values_to_save

    def validate_and_save(self, data: dict) -> dict:
        logger.info(f"Validating settings for section {self.category_slug if self.category_slug else 'all'}")

        validated_fields, errors, values_to_save = self.process_fields(data)
        # Search for user sending us additional random data
        if data.keys() != validated_fields.keys():
            for additional_key in list(set(data.keys()) - set(validated_fields.keys())):
                errors[additional_key] = _("Invalid key for category %(category_slug)s") % {"category_slug": self.category_slug}

        if errors:
            raise serializers.ValidationError(errors)

        # Since we have made it here w/o errors we are cleared to save the values
        for key, value in values_to_save.items():
            # We are not validating the value again because we already did that above
            update_preference_value(value['section'], key, value['value'], validate=False)

        # It is not enough to return validated_fields, since on_update might have changed some other fields
        # Re-fetch the whole section
        return self.to_representation()


class SettingPreferenceSerializer(serializers.ModelSerializer):
    # This is the serializer for a specific preference (like /api/gateway/v1/settings/all/jwt_private_key)
    value = serializers.SerializerMethodField()

    class Meta:
        model = Preference
        fields = ['section', 'name', 'value']

    @extend_schema_field(field=OpenApiTypes.ANY)
    def get_value(self, obj):
        if obj.preference.encrypted:
            return ENCRYPTED_STRING
        return obj.value
