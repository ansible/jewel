import logging

from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from ansible_base.lib.utils.settings import is_aoc_instance
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
from dynamic_preferences import types
from dynamic_preferences.serializers import SerializationError
from rest_framework import serializers

from aap_gateway_api.preferences import gateway_preference_registry
from aap_gateway_api.preferences.types import IntRangePreference, PEMPrivateKeyPreference, URLPreference
from aap_gateway_api.utils import get_preference_value_by_preference, update_preference_value

logger = logging.getLogger('aap.gateway.serializers.preferences')


class SettingSectionSerializer(serializers.Serializer):
    """Serialize setting category"""

    url = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)


class SettingSingletonSerializer(serializers.Serializer):
    def __init__(self, category_slug=None, *args, **kwargs):
        if category_slug == 'all':
            self.category_slug = None
        else:
            self.category_slug = category_slug
        super().__init__(None, *args, **kwargs)

    def setting_is_cloud_readonly(self, setting_name: str) -> bool:
        return is_aoc_instance() and setting_name in getattr(settings, 'AOC_UNCHANGEABLE_PREFERENCES', [])

    def get_fields(self) -> dict:
        # TODO: Maybe move this somewhere
        preference_type_to_field_mapping = {
            types.StringPreference: serializers.CharField,
            types.IntegerPreference: serializers.IntegerField,
            types.BooleanPreference: serializers.BooleanField,
            types.DecimalPreference: serializers.DecimalField,
            types.FloatPreference: serializers.FloatField,
            types.LongStringPreference: serializers.CharField,
            types.ChoicePreference: serializers.ChoiceField,
            types.ModelChoicePreference: serializers.PrimaryKeyRelatedField,
            types.ModelMultipleChoicePreference: serializers.PrimaryKeyRelatedField,
            types.FilePreference: serializers.FileField,
            types.DurationPreference: serializers.DurationField,
            types.DatePreference: serializers.DateField,
            types.DateTimePreference: serializers.DateTimeField,
            types.TimePreference: serializers.TimeField,
            types.MultipleChoicePreference: serializers.MultipleChoiceField,
            URLPreference: serializers.URLField,
            PEMPrivateKeyPreference: serializers.CharField,
            IntRangePreference: serializers.IntegerField,
        }

        long_string_fields = (
            types.LongStringPreference,
            PEMPrivateKeyPreference,
        )

        fields = super().get_fields()
        for registered_preference in gateway_preference_registry.preferences(self.category_slug):
            constructor = preference_type_to_field_mapping.get(registered_preference.field_type, serializers.Field)
            read_only = registered_preference.read_only or self.setting_is_cloud_readonly(registered_preference.name)

            fields[registered_preference.name] = constructor(
                initial=get_preference_value_by_preference(registered_preference),
                help_text=registered_preference.help_text,
                # No option being passed through the category is required because we might only be updating one.
                required=False,
                default=registered_preference.default,
                style={"base_template": "textarea.html"} if registered_preference.field_type in long_string_fields else None,
                read_only=read_only,
            )
            for field_name in ['max_value', 'min_value']:
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

    def process_fields(self, data: dict) -> (dict, dict, dict):
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

            if current_value != new_value and registered_preference.read_only:
                # We are trying to change a read only setting
                errors[registered_preference.name] = _("Cannot change read-only setting %(registered_preference_name)s") % {
                    "registered_preference_name": registered_preference.name
                }
                continue

            if current_value != new_value and self.setting_is_cloud_readonly(registered_preference.name):
                errors[registered_preference.name] = _("Cannot be changed in AoC environment")
                continue

            if current_value != new_value and new_value != ENCRYPTED_STRING:
                masked_value = new_value
                if registered_preference.encrypted:
                    masked_value = ENCRYPTED_STRING
                logger.debug(f"Validating value change from {current_value} to {masked_value} for {registered_preference.name}")
                try:
                    # Try to let the preference's class serializer convert the value (will raise if not valid)
                    # this method expects a string in case of a boolean value, so we have to convert it to pass validation
                    new_value = registered_preference.serializer.to_python(str(new_value))
                    registered_preference.validate(new_value)

                    # There are a couple scenarios this does not catch
                    if issubclass(registered_preference.__class__, types.IntegerPreference):
                        if type(new_value) is not int:
                            raise SerializationError("Must be an integer")
                    elif issubclass(registered_preference.__class__, types.StringPreference):
                        if type(new_value) is not str:
                            raise SerializationError("Must be a string")

                    # Mark the setting to be saved
                    values_to_save[registered_preference.name] = {'value': new_value, 'section': registered_preference.section.name}
                    validated_fields[registered_preference.name] = masked_value
                except (SerializationError, serializers.ValidationError, ValidationError) as e:
                    if isinstance(e, ValidationError):
                        e = ', '.join(e.messages)
                    errors[registered_preference.name] = str(e)

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
