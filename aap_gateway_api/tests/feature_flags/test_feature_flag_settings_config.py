import pytest
from django.conf import settings
from django.test import override_settings
from flags.sources import get_flags


def test_flags_configuration_exists():
    """Test that FLAGS dictionary is properly configured in settings"""
    assert hasattr(settings, 'FLAGS')
    assert isinstance(settings.FLAGS, dict)


@pytest.mark.django_db
def test_flags_structure():
    """Test that flag conditions have correct structure when set"""
    test_settings = {'TEST_FLAG': [{'condition': 'boolean', 'value': True}, {'condition': 'feature', 'value': 'OTHER_FLAG'}]}
    with override_settings(FLAGS=test_settings):
        flags = get_flags()
        conditions = flags['TEST_FLAG'].conditions
        assert isinstance(conditions, list)
        assert conditions[0].condition == 'boolean'
        assert conditions[1].condition == 'feature'


@pytest.mark.django_db
def test_invalid_flag_conditions():
    """Test various invalid flag condition scenarios"""
    # Test missing required 'condition' key
    with override_settings(FLAGS={'INVALID_FLAG': [{'value': True}]}):
        with pytest.raises(KeyError, match='condition'):
            get_flags()

    # Test missing required 'value' key
    with override_settings(FLAGS={'INVALID_FLAG': [{'condition': 'boolean'}]}):
        with pytest.raises(KeyError, match='value'):
            get_flags()
