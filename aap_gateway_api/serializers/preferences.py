import logging
from typing import Any, Optional

from ansible_base.lib.serializers.mixins import (
    _LOG_CONTROL_RE,  # noqa: F401 — shared constant
    CleanTextMixin,
)
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from ansible_base.lib.utils.settings import get_setting
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

# Fields excluded from CleanText validation because they legitimately contain
# HTML (custom_login_info) or binary/image data (custom_logo).
_CLEAN_TEXT_EXCLUDED_FIELDS = frozenset({'custom_login_info', 'custom_logo'})


class _PreferenceModelStub:
    """Minimal namespace providing ``_meta.app_label`` and ``_meta.object_name``.

    ``_log_validation_failure`` references ``_PreferenceModelStub._meta``
    directly (class-level access) to build the resource-type string for
    audit-log messages.  SettingSectionSerializer has no real Django model,
    so this stub supplies just enough surface area for the log line.
    """

    class _meta:
        app_label = 'aap_gateway_api'
        object_name = 'Preference'


class PlainSerializerCleanTextMixin(CleanTextMixin):
    """CleanTextMixin adaptation for plain (non-ModelSerializer) serializers.

    Inherits JSON-recursion helpers, depth-limiting, text validation, and audit
    logging from DAB's :class:`CleanTextMixin` while providing a
    preference-specific entry point (``_clean_text_validate``) that dispatches
    on runtime value types instead of model field introspection.

    Overrides:

    * ``validate()`` — bypasses the model-backed validation path.
      Preference validation is driven by ``validate_and_save()`` →
      ``_run_clean_text_on_pending_saves()`` → ``_clean_text_validate()``.
    * ``_log_validation_failure()`` — uses a static model stub since
      ``SettingSectionSerializer`` has no ``Meta.model``.
    """

    excluded_fields = _CLEAN_TEXT_EXCLUDED_FIELDS
    # Preferences don't have name-type fields; all text gets Tier 2 validation.
    name_fields = frozenset()

    def validate(self, attrs):
        """Bypass CleanTextMixin.validate() — no model introspection.

        Preference validation is driven by ``validate_and_save()`` →
        ``_run_clean_text_on_pending_saves()`` → ``_clean_text_validate()``.
        """
        # Skip CleanTextMixin.validate (which references self.Meta.model);
        # go directly to the base Serializer.validate.
        return super(CleanTextMixin, self).validate(attrs)

    def _log_validation_failure(self, field_name, detail):
        """Emit a WARNING-level audit log for a rejected preference value.

        Overrides ``CleanTextMixin._log_validation_failure`` to use a static
        model stub instead of ``self.Meta.model``.
        """
        resource_type = f"{_PreferenceModelStub._meta.app_label}.{_PreferenceModelStub._meta.object_name}"
        if isinstance(detail, list):
            reason = '; '.join(str(d) for d in detail)
        else:
            reason = str(detail)
        reason = _LOG_CONTROL_RE.sub(lambda m: repr(m.group())[1:-1], reason)
        logger.warning(
            "Validation rejected '%s' on %s: %s",
            field_name,
            resource_type,
            reason,
        )

    def _clean_text_validate(self, changed_values, stored_values):
        """Validate text content in *changed* preference values.

        Args:
            changed_values: dict mapping preference name → new parsed value.
            stored_values: dict mapping preference name → current stored value
                           (used for grandfathering unchanged nested leaves).

        Returns:
            dict of field-name → error detail, empty when all values pass.
        """
        if not get_setting('ENHANCED_INPUT_VALIDATION_ENABLED', False):
            return {}

        errors = {}
        serializer_fields = self.get_fields()

        for field_name, new_value in changed_values.items():
            if field_name in self.excluded_fields:
                continue

            field = serializer_fields.get(field_name)
            if field is None:
                continue

            stored = stored_values.get(field_name)

            self._validate_field_value(field_name, new_value, stored, errors)

        return errors

    def _validate_field_value(self, field_name, new_value, stored, errors):
        """Dispatch validation for a single preference value by runtime type.

        Delegates to inherited DAB helpers:

        * ``_run_text_validator`` for top-level strings (Tier 2 only;
          ``name_fields`` is empty).
        * ``_validate_json_list`` / ``_validate_json_dict`` for nested
          structures (called with ``skip_keys=frozenset()``).
        """
        if isinstance(new_value, str):
            # Top-level string value (CharField, URLField, etc.)
            if new_value != stored:
                # Inherited from CleanTextMixin — routes to validate_free_text
                # (Tier 2) since name_fields is empty.
                self._run_text_validator(field_name, new_value, errors)
        elif isinstance(new_value, list):
            json_errors = {}
            # Inherited from CleanTextMixin — pass empty skip_keys and a
            # fresh errors dict; wrap under field_name if any errors found.
            self._validate_json_list(
                new_value,
                frozenset(),
                json_errors,
                field_name=field_name,
                stored_data=stored,
            )
            if json_errors:
                errors[field_name] = json_errors
        elif isinstance(new_value, dict):
            json_errors = {}
            self._validate_json_dict(
                new_value,
                frozenset(),
                json_errors,
                field_name=field_name,
                stored_data=stored,
            )
            if json_errors:
                errors[field_name] = json_errors


class SettingSectionListSerializer(serializers.Serializer):
    # This is the serializer for the list of categories (/api/gateway/v1/settings)
    """Serialize list of settings category"""

    url = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)


class SettingSectionSerializer(PlainSerializerCleanTextMixin, serializers.Serializer):
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
                values_to_save[registered_preference.name] = {
                    'value': parsed_value,
                    'section': registered_preference.section.name,
                    'persisted_value': current_value,
                }
                validated_fields[registered_preference.name] = masked_value

        return validated_fields, errors, values_to_save

    def _build_encrypted_field_set(self):
        """Return the set of preference names that are encrypted."""
        return frozenset(pref.name for pref in gateway_preference_registry.preferences(self.category_slug) if pref.encrypted)

    def _run_clean_text_on_pending_saves(self, values_to_save):
        """Build clean-text inputs from pending saves and run validation.

        Skips encrypted preferences (their values should not be inspected)
        and provides persisted values for grandfathering unchanged leaves.

        Returns:
            dict of field-name → error detail, or empty dict when all pass.
        """
        if not values_to_save:
            return {}

        encrypted_fields = self._build_encrypted_field_set()
        changed_for_clean = {}
        stored_for_clean = {}
        for pref_name, save_info in values_to_save.items():
            if pref_name in encrypted_fields:
                continue
            changed_for_clean[pref_name] = save_info['value']
            # Use the persisted value captured before process_fields
            # overwrote validated_fields with the submitted value.
            stored_for_clean[pref_name] = save_info.get('persisted_value')

        if not changed_for_clean:
            return {}

        return self._clean_text_validate(changed_for_clean, stored_for_clean)

    def validate_and_save(self, data: dict) -> dict:
        logger.info(f"Validating settings for section {self.category_slug if self.category_slug else 'all'}")

        validated_fields, errors, values_to_save = self.process_fields(data)
        # Search for user sending us additional random data
        if data.keys() != validated_fields.keys():
            for additional_key in set(data.keys()) - set(validated_fields.keys()):
                errors[additional_key] = _("Invalid key for category %(category_slug)s") % {"category_slug": self.category_slug}

        if errors:
            raise serializers.ValidationError(errors)

        # CleanText validation on pending saves (skips encrypted prefs,
        # uses persisted values for grandfathering).
        clean_errors = self._run_clean_text_on_pending_saves(values_to_save)
        if clean_errors:
            raise serializers.ValidationError(clean_errors)

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
