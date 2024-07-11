import pytest
from django.core.exceptions import ValidationError

from aap_gateway_api.preferences.types import IntRangePreference


@pytest.mark.parametrize(
    "min_value,max_value",
    [
        (None, None),
        (7, None),
        (None, 7),
        (2, 87654321),
    ],
)
def test_min_max_value_of_int_range_type(min_value, max_value, register_preference, set_preference):
    kwargs = {}
    if min_value:
        kwargs['min_value'] = min_value
        fail_low_value = min_value - 1
        pass_low_value = min_value
    else:
        fail_low_value = IntRangePreference.DEFAULT_MIN_VALUE - 1
        pass_low_value = IntRangePreference.DEFAULT_MIN_VALUE
    if max_value:
        kwargs['max_value'] = max_value
        fail_high_value = max_value + 1
        pass_high_value = max_value
    else:
        fail_high_value = IntRangePreference.DEFAULT_MAX_VALUE + 1
        pass_high_value = IntRangePreference.DEFAULT_MAX_VALUE

    register_preference(
        section="general",
        preference_name="test_preference",
        default=7,
        required=False,
        encrypted=False,
        preference_type="int_range",
        help_text="This is a test preference",
        **kwargs,
    )

    with pytest.raises(ValidationError):
        set_preference("general", "test_preference", fail_low_value)
    set_preference("general", "test_preference", pass_low_value)
    set_preference("general", "test_preference", pass_high_value)
    with pytest.raises(ValidationError):
        set_preference("general", "test_preference", fail_high_value)
