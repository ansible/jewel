import logging

from dynamic_preferences.serializers import SerializationError
from rest_framework import serializers

from aap_gateway_api.models import gateway_preference_registry
from aap_gateway_api.utils import ENCRYPTED_STRING, get_preference_value_by_preference, update_preference_value

logger = logging.getLogger('aap.gateway.serializers')


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

    def get_fields(self) -> dict:
        from rest_framework.fields import Field

        fields = super().get_fields()
        for registered_preference in gateway_preference_registry.preferences(self.category_slug):
            fields[registered_preference.name] = Field(
                initial=get_preference_value_by_preference(registered_preference),
                help_text=registered_preference.help_text,
                # No option being passed through the category is required because we might on;y be updating one.
                required=False,
                default=registered_preference.default,
            )

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

            if current_value != new_value and new_value != ENCRYPTED_STRING:
                masked_value = new_value
                if registered_preference.encrypted:
                    masked_value = ENCRYPTED_STRING
                logger.debug(f"Validating value change from {current_value} to {masked_value} for {registered_preference.name}")
                try:
                    # Try to let the preference's class serializer convert the value (will raise if not valid)
                    registered_preference.serializer.to_db(new_value)
                    # Mark the setting to be saved
                    values_to_save[registered_preference.name] = {'value': new_value, 'section': registered_preference.section.name}
                    validated_fields[registered_preference.name] = masked_value
                except SerializationError as e:
                    # If we failed append to our errors
                    errors[registered_preference.name] = e

        return validated_fields, errors, values_to_save

    def validate_and_save(self, data: dict) -> dict:
        logger.info(f"Validating settings for section {self.category_slug if self.category_slug else 'all'}")

        validated_fields, errors, values_to_save = self.process_fields(data)

        # Search for user sending us additional random data
        if data.keys() != validated_fields.keys():
            for additional_key in list(set(data.keys()) - set(validated_fields.keys())):
                errors[additional_key] = f'Invalid key for category {self.category_slug}'

        if errors:
            raise serializers.ValidationError(errors)

        # Since we have made it here w/o errors we are cleared to save the values
        for key, value in values_to_save.items():
            update_preference_value(value['section'], key, value['value'])

        return validated_fields
