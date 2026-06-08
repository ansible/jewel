from unittest import mock

import pytest
from ansible_base.feature_flags.models import AAPFlag
from ansible_base.feature_flags.utils import create_initial_data as seed_feature_flags

from aap_gateway_api.models import Organization, ServiceType
from aap_gateway_api.signals.preloaded_data import add_console_service_type, create_default_organization, create_preload_data, set_system_user_password


class TestCreatePreloadedData:
    @pytest.mark.django_db
    def test_create_default_organization(self):
        Organization.objects.all().delete()
        assert create_default_organization() is True, "We should have created the default organization"
        assert create_default_organization() is False, "We should not have recreated the default organization"

    @pytest.mark.django_db
    def test_set_system_user_password(self):
        """set_system_user_password returns True when password was usable, False when already unusable."""
        from ansible_base.lib.utils.models import get_system_user

        # Ensure the system user starts with a usable password
        system_user = get_system_user()
        system_user.set_password("temporary")
        system_user.save()

        assert set_system_user_password() is True, "Should set unusable password on first call"
        assert set_system_user_password() is False, "Should be a no-op when password is already unusable"

    @pytest.mark.django_db
    def test_default_org_created_by_default(self):
        org = Organization.objects.filter(name='Default')
        assert org

    @pytest.mark.django_db
    def test_immediate_return_if_no_plan(self):
        Organization.objects.all().delete()
        create_preload_data()
        assert Organization.objects.count() == 0

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "verbosity",
        [
            0,
            1,
        ],
    )
    def test_no_run_on_rollback(self, verbosity, expected_log):
        Organization.objects.all().delete()
        with expected_log('aap_gateway_api.signals.preloaded_data.logger', 'debug', 'We are rolling back migration', assert_not_called=(not verbosity)):
            create_preload_data(verbosity=verbosity, plan=[('0000', False), ('0001', True)])
        assert Organization.objects.count() == 0

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "verbosity,log_level",
        [
            (0, 'error'),
            (1, 'error'),
            (2, 'exception'),
        ],
    )
    def test_exception_raised_during_create(self, verbosity, log_level, expected_log):
        mock_function = mock.MagicMock()
        mock_function.__name__ = 'create_default_organization'
        mock_function.side_effect = Exception('Failed')
        with mock.patch('aap_gateway_api.signals.preloaded_data.create_default_organization', mock_function):
            with expected_log('aap_gateway_api.signals.preloaded_data.logger', log_level, 'Failed to'):
                create_preload_data(verbosity=verbosity, plan=[('0000', False)])

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "flag_value",
        [
            'True',
            'False',
        ],
    )
    def test_console_st(self, flag_value, settings_override_mutable, settings):
        with pytest.raises(ServiceType.DoesNotExist):
            ServiceType.objects.get(name="console")
        AAPFlag.objects.all().delete()
        setattr(settings, "FEATURE_GATEWAY_CREATE_CRC_SERVICE_TYPE_ENABLED", flag_value)
        seed_feature_flags()

        if flag_value == 'False':
            assert add_console_service_type() is False
            with pytest.raises(ServiceType.DoesNotExist):
                ServiceType.objects.get(name="console")
        else:
            assert add_console_service_type() is True
            # Second call should return False (already exists)
            assert add_console_service_type() is False

            console_type = ServiceType.objects.get(name="console")

            assert console_type.name == "console"
            assert console_type.ping_url is None
            assert console_type.service_index_path is None
            assert console_type.login_path is None
            assert console_type.logout_path is None
