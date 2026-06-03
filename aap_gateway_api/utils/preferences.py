import logging
from typing import Any, Optional

from ansible_base.lib.utils.encryption import ENCRYPTED_STRING, ansible_encryption
from ansible_base.lib.utils.settings import SettingNotSetException, is_aoc_instance
from django.conf import settings
from django.utils.translation import gettext as _
from dynamic_preferences import types
from dynamic_preferences.preferences import Section
from rest_framework import serializers

from aap_gateway_api.fields.serializers import JSONListField
from aap_gateway_api.preferences import gateway_preference_registry
from aap_gateway_api.preferences.serializers import JSONString
from aap_gateway_api.preferences.types import (
    AbsolutePathOrURLPreference,
    CSRFListPreference,
    FloatRangePreference,
    IntRangePreference,
    JSONPreference,
    MimeTypedImagePreference,
    PEMPrivateKeyPreference,
    StringListPreference,
    URLPreference,
)

gateway_preference_manager = gateway_preference_registry.manager()
separator = getattr(settings, 'DYNAMIC_PREFERENCES', {}).get('SECTION_KEY_SEPARATOR', '__')

logger = logging.getLogger("aap.gateway.utils.preferences")


class TooManyPreferencesException(Exception):
    """Raised when multiple preferences match a single setting name lookup."""


def update_preference_value(section: str, name: str, value: str, validate: bool = True) -> None:
    if validate:
        preference = gateway_preference_registry.get(name, section)
        preference.validate(value)
    gateway_preference_registry.manager().update_db_pref(section, name, value)


def get_preference_value_by_preference(preference: object, encrypted: bool = True) -> str:
    return get_preference_value(preference.section.name, preference.name, encrypted)


def get_encrypted_string_for_preference(preference: object) -> str:
    # JSONPreferences and their subclasses need this to attach breadcrumbs for proper HTML form rendering
    if isinstance(preference, JSONPreference):
        return JSONString(ENCRYPTED_STRING)
    return ENCRYPTED_STRING


def get_default_value_by_preference(preference: object, encrypted: bool = True) -> str:
    if encrypted:
        return get_encrypted_string_for_preference(preference)
    return getattr(preference, 'default', None)


def get_preference_key(section: str, name: str) -> str:
    return f"{section}{separator}{name}"


def get_preference_value(section: str, name: str, encrypted: bool = True) -> str:
    if not section or not name:
        raise ValueError(_("You must pass get_preference_value a section and a name"))

    # Return setting value for settings bound prefs or drop through to default value if not found
    if gateway_preference_registry.get(name, section).settings_bound:
        setting_val = getattr(settings, name, None)
        if setting_val is not None:
            return setting_val
        raise ValueError(_("A settings_bound preference can not have a None value"))

    preference_name = get_preference_key(section, name)
    value = gateway_preference_registry.manager().get(preference_name)

    if (preference := gateway_preference_registry.get(name, section)).encrypted:
        if encrypted:
            return get_encrypted_string_for_preference(preference)
        # Note: values can be retrieved from cache instead of the DB.
        # However, decrypt_string() can identify encrypted values and decrypt them,
        # returning the non encrypted values unchanged.
        value = ansible_encryption.decrypt_string(value)

    return value


def get_preference_sections() -> [Section]:
    return list(gateway_preference_registry.sections())


sections = {}

# Maps preference type classes to their corresponding DFR serializer fields
PREFERENCE_TYPE_CLASS_TO_SERIALIZER_FIELD_MAPPING = {
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
    AbsolutePathOrURLPreference: serializers.URLField,
    PEMPrivateKeyPreference: serializers.CharField,
    IntRangePreference: serializers.IntegerField,
    FloatRangePreference: serializers.FloatField,
    MimeTypedImagePreference: serializers.CharField,
    JSONPreference: serializers.JSONField,
    StringListPreference: JSONListField,
    CSRFListPreference: JSONListField,
}

# Maps string-based type identifiers to their corresponding preference type classes
_PREFERENCE_TYPE_NAME_TO_CLASS_MAPPING = {
    "string": types.StringPreference,
    "longstring": types.LongStringPreference,
    "int": types.IntegerPreference,
    "bool": types.BooleanPreference,
    "url": URLPreference,
    "absolute_path_or_url": AbsolutePathOrURLPreference,
    "pem_private_key": PEMPrivateKeyPreference,
    "image": MimeTypedImagePreference,
    "int_range": IntRangePreference,
    "float_range": FloatRangePreference,
    "json": JSONPreference,
    "string_list": StringListPreference,
    "CSRF_list": CSRFListPreference,
}


def register(
    section="general",
    preference_name=None,
    default=None,
    required=False,
    encrypted=False,
    preference_type="string",
    help_text=_("No help text specified"),
    read_only=False,
    label=None,
    on_update=None,
    settings_bound=False,
    **kwargs,
):
    if not preference_name:
        raise NameError(_("A preference must have a name"))

    if preference_type not in _PREFERENCE_TYPE_NAME_TO_CLASS_MAPPING:
        raise NotImplementedError(_("Preference type %(preference_type)s is not yet implemented in preferences utils") % {"preference_type": preference_type})

    if section not in sections:
        sections[section] = Section(section)

    if settings_bound and not read_only:
        read_only = True
        logger.warning(f"Setting {preference_name} was set as settings_bound but not marked as read_only. Altering setting to be read only")
    type_class = _PREFERENCE_TYPE_NAME_TO_CLASS_MAPPING[preference_type]

    class_name = f'{(preference_name.title())}_Preference'

    preference_details = {
        "section": sections[section],
        "name": preference_name,
        "default": default,
        "required": required,
        "encrypted": encrypted,
        "field_type": type_class,
        "help_text": help_text,
        "read_only": read_only,
        "label": label,
        "on_update": on_update,
        "settings_bound": settings_bound,
    }
    preference_details.update(kwargs)
    my_transient_class = type(
        class_name,
        (type_class,),
        preference_details,
    )
    gateway_preference_registry.register(my_transient_class)

    return my_transient_class


def initialize_preferences():
    # This method is called from apps.py to initialize all preferences in the database
    # This seems like a really weird function let me explain...
    # When a preference is accessed the library code will:
    #    check the cache if available
    #    check the db
    #    create in the db if needed
    # So we are going to loop over the preferences and ask for them one by one
    # This will force the values to be written to the DB if needed.
    # Which we need because on initial startup without this all of the preferences categories will just be blank
    # The global_preferences object looks like a dict, so the keys will be the preference names
    # Then we ask the global_preferences for the value of the key and it will take the actions above and populate our DB for us
    for preference_name in gateway_preference_manager.keys():
        gateway_preference_manager[preference_name]


def get_setting(name: str, encrypted: bool = True) -> Any:
    possible_preferences = []
    for preference in gateway_preference_registry.preferences():
        if preference.name == name:
            possible_preferences.append(preference)

    if len(possible_preferences) == 0:
        raise SettingNotSetException()
    elif len(possible_preferences) == 1:
        return get_preference_value_by_preference(possible_preferences[0], encrypted)
    else:
        raise TooManyPreferencesException(
            _("There were %(possible_preferences)s for setting %(name)s, unable to get a setting by name")
            % {"possible_preferences": len(possible_preferences), "name": name}
        )


def is_read_only_preference(preference: object) -> tuple[bool, Optional[str]]:
    """
    Returns: tuple
        - bool: True if preference is read_only by setting or by AoC environment. False, otherwise
        - Optional[str]: appropriate message if read_only. None, otherwise
    """
    if preference.read_only:
        return True, _("%(preference_name)s is read-only by setting.") % {"preference_name": preference.name}

    if is_aoc_instance() and preference.name in getattr(settings, 'AOC_UNCHANGEABLE_PREFERENCES', []):
        return True, _("%(preference_name)s is read-only by AoC environment") % {"preference_name": preference.name}

    return False, None
