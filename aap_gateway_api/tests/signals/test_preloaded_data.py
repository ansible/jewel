from unittest import mock

import pytest

from aap_gateway_api.models import Organization, Preference, ServiceType
from aap_gateway_api.signals.preloaded_data import (
    create_default_organization,
    create_preload_data,
    remove_console_service_type,
    set_system_user_managed_flag,
    set_system_user_password,
)


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
    def test_set_system_user_managed_flag(self):
        from ansible_base.lib.utils.models import get_system_user

        system_user = get_system_user()
        system_user.managed = False
        system_user.save()
        assert set_system_user_managed_flag() is True, "Should set managed=True when unset"
        assert set_system_user_managed_flag() is False, "Should be no-op when already managed"

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
    def test_remove_console_service_type(self):
        """remove_console_service_type deletes console ServiceType and RED_HAT_CONSOLE_URL preference."""
        ServiceType.objects.get_or_create(name="console")
        Preference.objects.bulk_create(
            [Preference(section="analytics", name="RED_HAT_CONSOLE_URL", raw_value="https://console.redhat.com")],
            ignore_conflicts=True,
        )

        assert remove_console_service_type() is True, "Should delete existing records"
        assert not ServiceType.objects.filter(name="console").exists()
        assert not Preference.objects.filter(section="analytics", name="RED_HAT_CONSOLE_URL").exists()

    @pytest.mark.django_db
    def test_remove_console_service_type_idempotent(self):
        """remove_console_service_type is a no-op when records don't exist."""
        ServiceType.objects.filter(name="console").delete()
        Preference.objects.filter(section="analytics", name="RED_HAT_CONSOLE_URL").delete()

        assert remove_console_service_type() is False, "Should return False when nothing to delete"

    @pytest.mark.django_db
    def test_remove_console_service_type_only_service_type(self):
        """remove_console_service_type handles case where only ServiceType exists."""
        Preference.objects.filter(section="analytics", name="RED_HAT_CONSOLE_URL").delete()
        ServiceType.objects.get_or_create(name="console")

        assert remove_console_service_type() is True
        assert not ServiceType.objects.filter(name="console").exists()

    @pytest.mark.django_db
    def test_remove_console_service_type_only_preference(self):
        """remove_console_service_type handles case where only Preference exists."""
        ServiceType.objects.filter(name="console").delete()
        Preference.objects.bulk_create(
            [Preference(section="analytics", name="RED_HAT_CONSOLE_URL", raw_value="https://console.redhat.com")],
            ignore_conflicts=True,
        )

        assert remove_console_service_type() is True
        assert not Preference.objects.filter(section="analytics", name="RED_HAT_CONSOLE_URL").exists()

    @pytest.mark.django_db
    def test_remove_console_service_type_via_preload_data(self):
        """remove_console_service_type is wired into create_preload_data function_order."""
        ServiceType.objects.get_or_create(name="console")
        Preference.objects.bulk_create(
            [Preference(section="analytics", name="RED_HAT_CONSOLE_URL", raw_value="https://console.redhat.com")],
            ignore_conflicts=True,
        )

        create_preload_data(verbosity=0, plan=[('0000', False)])

        assert not ServiceType.objects.filter(name="console").exists()
        assert not Preference.objects.filter(section="analytics", name="RED_HAT_CONSOLE_URL").exists()

    def test_remove_console_service_type_lookup_error(self):
        """remove_console_service_type returns False when models are not available."""
        with mock.patch('aap_gateway_api.signals.preloaded_data.global_apps.get_model', side_effect=LookupError):
            assert remove_console_service_type() is False

    @pytest.mark.django_db
    def test_remove_console_service_type_cascade_warning(self, expected_log):
        """remove_console_service_type logs warning when ServiceClusters will be cascade-deleted."""
        from aap_gateway_api.models import ServiceCluster

        st, _ = ServiceType.objects.get_or_create(name="console")
        ServiceCluster.objects.create(name="test-console-cluster", service_type=st)

        with expected_log('aap_gateway_api.signals.preloaded_data.logger', 'warning', 'Cascade-deleting'):
            assert remove_console_service_type() is True
        assert not ServiceType.objects.filter(name="console").exists()
        assert not ServiceCluster.objects.filter(name="test-console-cluster").exists()

    @pytest.mark.django_db
    def test_remove_console_service_type_cascade_check_exception(self):
        """remove_console_service_type handles cascade check failures gracefully."""
        ServiceType.objects.get_or_create(name="console")

        with mock.patch.object(
            ServiceType.objects.filter(name="console").__class__,
            'values_list',
            side_effect=Exception("query error"),
        ):
            assert remove_console_service_type() is True
        assert not ServiceType.objects.filter(name="console").exists()

    @pytest.mark.django_db
    def test_remove_console_service_type_logs_removed_action(self, expected_log):
        """create_preload_data logs 'Removed' action for remove_ functions."""
        ServiceType.objects.get_or_create(name="console")

        with expected_log('aap_gateway_api.signals.preloaded_data.logger', 'debug', 'Removed'):
            create_preload_data(verbosity=1, plan=[('0000', False)])
