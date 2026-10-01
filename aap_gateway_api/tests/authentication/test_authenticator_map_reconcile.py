import logging
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from ansible_base.authentication.utils.claims import load_reconcile_user_class


@pytest.mark.django_db
@patch('aap_gateway_api.authentication.reconcile.AllServicesClient')
def test_authenticator_map_grant_syncs_assignment_to_services(all_services_client):
    """A newly mapped role is pushed to components during login reconciliation."""
    from aap_gateway_api.authentication.reconcile import ReconcileUser

    user = SimpleNamespace(username='mapped-user')
    role_definition = Mock()
    assignment = Mock()
    role_definition.give_global_permission.return_value = assignment

    ReconcileUser({}, user, Mock())._give_permission(role_definition)

    all_services_client.assert_called_once_with(user=user, wait_for_response=False)
    callback_client = all_services_client.return_value.with_callback.return_value
    callback_client.sync_assignment.assert_called_once_with(assignment)


@pytest.mark.django_db
@patch('aap_gateway_api.authentication.reconcile.AllServicesClient')
def test_authenticator_map_sync_logs_service_rejection(all_services_client, caplog):
    """A failed component response is logged with enough context to diagnose it."""
    from aap_gateway_api.authentication.reconcile import ReconcileUser

    user = SimpleNamespace(username='mapped-user')
    role_definition = Mock()
    role_definition.give_global_permission.return_value = Mock()
    reconciler = ReconcileUser({}, user, Mock())

    reconciler._give_permission(role_definition)
    callback = all_services_client.return_value.with_callback.call_args.args[0]

    with caplog.at_level(logging.WARNING, logger='aap.gateway.authentication.reconcile'):
        callback(SimpleNamespace(api_slug='controller'), SimpleNamespace(status_code=400, text='invalid assignment'))

    assert 'Authenticator-map assignment sync to controller failed: HTTP 400: invalid assignment' in caplog.messages


@pytest.mark.django_db
def test_gateway_uses_syncing_authenticator_map_reconciler():
    """Gateway config selects its reconciler instead of DAB's no-sync default."""
    from aap_gateway_api.authentication.reconcile import ReconcileUser

    assert load_reconcile_user_class() is ReconcileUser
