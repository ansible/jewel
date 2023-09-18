from django.conf import settings
from dynamic_preferences import types
from dynamic_preferences.preferences import Section

from aap_gateway_api.models import gateway_preference_registry
from aap_gateway_api.preference_types import PEMPrivateKeyPreference, URLPreference
from aap_gateway_api.utils import ENCRYPTED_STRING

gateway_preference_manager = gateway_preference_registry.manager()
separator = getattr(settings, 'DYNAMIC_PREFERENCES', {}).get('SECTION_KEY_SEPARATOR', '__')


def update_preference_value(section: str, name: str, value: str, validate: bool = True) -> None:
    if validate:
        preference = gateway_preference_registry.get(name, section)
        preference.validate(value)
    gateway_preference_registry.manager().update_db_pref(section, name, value)


def get_preference_value_by_preference(preference: object, encrypted: bool = True) -> str:
    return get_preference_value(preference.section.name, preference.name, encrypted)


def get_preference_key(section: str, name: str) -> str:
    return f"{section}{separator}{name}"


def get_preference_value(section: str, name: str, encrypted: bool = True) -> str:
    if not section or not name:
        raise ValueError("You must pass get_preference_value a section and a name")

    preference_name = get_preference_key(section, name)
    if encrypted and gateway_preference_registry.get(name, section).encrypted:
        return ENCRYPTED_STRING

    return gateway_preference_registry.manager().get(preference_name)


def get_preference_sections() -> [Section]:
    return list(gateway_preference_registry.sections())


sections = {}
preference_type_mapping = {
    "string": types.StringPreference,
    "longstring": types.LongStringPreference,
    "int": types.IntegerPreference,
    "bool": types.BooleanPreference,
    "url": URLPreference,
    "pem_private_key": PEMPrivateKeyPreference,
}


def register(
    section="general",
    preference_name=None,
    default=None,
    required=False,
    encrypted=False,
    preference_type="string",
    help_text="No help text specified",
    read_only=False,
    on_update=None,
):
    if not preference_name:
        raise NameError("A preference must have a name")

    if preference_type not in preference_type_mapping:
        raise NotImplementedError(f"Preference type {preference_type} is not yet implemented in preferences utils")

    if section not in sections:
        sections[section] = Section(section)

    type_class = preference_type_mapping[preference_type]

    class_name = f'{(preference_name.title())}_Preference'

    my_transient_class = type(
        class_name,
        (type_class,),
        {
            "section": sections[section],
            "name": preference_name,
            "default": default,
            "required": required,
            "encrypted": encrypted,
            "field_type": type_class,
            "help_text": help_text,
            "read_only": read_only,
            "on_update": on_update,
        },
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
