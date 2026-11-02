import importlib
import warnings

import pytest
from django.apps import apps

from aap_gateway_api.models import Preference

_migration = importlib.import_module("aap_gateway_api.migrations.0021_remove_runtime_feature_flags_ui_preference")
remove_preference = _migration.remove_runtime_feature_flags_ui_preference
restore_preference = _migration.restore_runtime_feature_flags_ui_preference

TARGET_SECTION = "feature_flags"
TARGET_NAME = "RUNTIME_FEATURE_FLAGS_UI"


def create_preference(section, name, value):
    row = Preference(section=section, name=name, raw_value=value)
    Preference.objects.bulk_create([row])
    return row


@pytest.mark.parametrize("target_exists", [False, True], ids=["target-absent", "target-present"])
def test_forward_deletes_only_exact_runtime_feature_flag_preference(db, target_exists):
    Preference.objects.filter(section=TARGET_SECTION, name=TARGET_NAME).delete()
    if target_exists:
        create_preference(TARGET_SECTION, TARGET_NAME, "synthetic-target-value")
    same_name_other_section = create_preference("other_section", TARGET_NAME, "keep-other-section")
    same_section_other_name = create_preference(TARGET_SECTION, "UNRELATED_FEATURE_FLAG", "keep-other-name")

    remove_preference(apps, None)

    assert not Preference.objects.filter(section=TARGET_SECTION, name=TARGET_NAME).exists()
    same_name_other_section.refresh_from_db()
    same_section_other_name.refresh_from_db()
    assert (same_name_other_section.section, same_name_other_section.name, same_name_other_section.raw_value) == (
        "other_section",
        TARGET_NAME,
        "keep-other-section",
    )
    assert (same_section_other_name.section, same_section_other_name.name, same_section_other_name.raw_value) == (
        TARGET_SECTION,
        "UNRELATED_FEATURE_FLAG",
        "keep-other-name",
    )


def test_reverse_warns_and_does_not_fabricate_preference_row(db):
    Preference.objects.filter(section=TARGET_SECTION, name=TARGET_NAME).delete()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        restore_preference(apps, None)

    assert len(caught) == 1
    assert TARGET_NAME in str(caught[0].message)
    assert not Preference.objects.filter(section=TARGET_SECTION, name=TARGET_NAME).exists()
