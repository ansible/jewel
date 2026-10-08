import logging
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from ansible_base.authentication.utils.claims import ReconcileUser as BaseReconcileUser
from ansible_base.authentication.utils.claims import load_reconcile_user_class


@pytest.mark.django_db
@patch('aap_gateway_api.authentication.reconcile.AllServicesClient')
def test_multiple_authenticator_map_grants_sync_once(all_services_client, monkeypatch):
    """Multiple newly mapped roles are sent as one batch after local reconciliation."""
    from aap_gateway_api.authentication.reconcile import ReconcileUser

    user = SimpleNamespace(username='mapped-user')
    role_one = Mock()
    role_two = Mock()
    assignment_one = Mock()
    assignment_two = Mock()
    role_one.give_global_permission.return_value = assignment_one
    role_two.give_global_permission.return_value = assignment_two

    def apply_permissions(reconciler):
        assert reconciler._give_permission(role_one) is assignment_one
        assert reconciler._give_permission(role_two) is assignment_two

    monkeypatch.setattr(BaseReconcileUser, 'apply_permissions', apply_permissions)
    ReconcileUser({}, user, Mock()).apply_permissions()

    all_services_client.assert_called_once_with(user=user, wait_for_response=False)
    callback_client = all_services_client.return_value.with_callback.return_value
    callback_client.sync_assignments.assert_called_once_with([assignment_one, assignment_two])
    callback_client.sync_assignment.assert_not_called()


@pytest.mark.django_db
@patch('aap_gateway_api.authentication.reconcile.AllServicesClient')
def test_multiple_authenticator_map_removals_sync_once(all_services_client, monkeypatch):
    """Removed mapped roles are collected before local removal and sent as one batch."""
    from aap_gateway_api.authentication.reconcile import ReconcileUser

    user = SimpleNamespace(username='mapped-user')
    organization = SimpleNamespace(id=17)
    role_one = Mock()
    role_two = Mock()

    def apply_permissions(reconciler):
        reconciler._remove_permission(role_one)
        reconciler._remove_permission(role_two, organization)

    monkeypatch.setattr(BaseReconcileUser, 'apply_permissions', apply_permissions)
    ReconcileUser({}, user, Mock()).apply_permissions()

    all_services_client.assert_called_once_with(user=user, wait_for_response=False)
    callback_client = all_services_client.return_value.with_callback.return_value
    callback_client.sync_unassignments.assert_called_once_with([(role_one, user, None), (role_two, user, organization)])


@pytest.mark.django_db
@patch('aap_gateway_api.authentication.reconcile.AllServicesClient')
def test_mixed_authenticator_map_changes_sync_as_two_batches(all_services_client, monkeypatch):
    """One reconciliation sends at most one grant and one removal batch."""
    from aap_gateway_api.authentication.reconcile import ReconcileUser

    user = SimpleNamespace(username='mapped-user')
    assignment = Mock()
    grant_role = Mock()
    grant_role.give_global_permission.return_value = assignment
    removal_role = Mock()

    def apply_permissions(reconciler):
        reconciler._give_permission(grant_role)
        reconciler._remove_permission(removal_role)

    monkeypatch.setattr(BaseReconcileUser, 'apply_permissions', apply_permissions)
    ReconcileUser({}, user, Mock()).apply_permissions()

    all_services_client.assert_called_once_with(user=user, wait_for_response=False)
    callback_client = all_services_client.return_value.with_callback.return_value
    callback_client.sync_assignments.assert_called_once_with([assignment])
    callback_client.sync_unassignments.assert_called_once_with([(removal_role, user, None)])
    assert all_services_client.return_value.with_callback.call_count == 2


@pytest.mark.django_db
@patch('aap_gateway_api.authentication.reconcile.AllServicesClient')
def test_empty_authenticator_map_reconciliation_does_not_create_sync_client(all_services_client, monkeypatch):
    from aap_gateway_api.authentication.reconcile import ReconcileUser

    monkeypatch.setattr(BaseReconcileUser, 'apply_permissions', lambda reconciler: None)
    ReconcileUser({}, SimpleNamespace(username='mapped-user'), Mock()).apply_permissions()

    all_services_client.assert_not_called()


@pytest.mark.django_db
@patch('aap_gateway_api.authentication.reconcile.AllServicesClient')
def test_authenticator_map_grant_without_assignment_does_not_create_sync_client(all_services_client, monkeypatch):
    from aap_gateway_api.authentication.reconcile import ReconcileUser

    role_definition = Mock()
    role_definition.give_global_permission.return_value = None

    def apply_permissions(reconciler):
        reconciler._give_permission(role_definition)

    monkeypatch.setattr(BaseReconcileUser, 'apply_permissions', apply_permissions)
    ReconcileUser({}, SimpleNamespace(username='mapped-user'), Mock()).apply_permissions()

    all_services_client.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('callback_name', 'log_subject'),
    [('_log_sync_result', 'assignment'), ('_log_unassignment_sync_result', 'unassignment')],
)
def test_authenticator_map_sync_logs_service_rejection(caplog, callback_name, log_subject):
    """The callback preserves sync context without duplicating the response body."""
    from aap_gateway_api.authentication.reconcile import ReconcileUser

    callback = getattr(ReconcileUser, callback_name)
    response_body = 'x' * 2048

    with caplog.at_level(logging.WARNING, logger='aap.gateway.authentication.reconcile'):
        callback(SimpleNamespace(api_slug='controller'), SimpleNamespace(status_code=400, text=response_body))

    assert f'Authenticator-map {log_subject} sync to controller failed: HTTP 400' in caplog.messages
    assert response_body not in caplog.text


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('callback_name', 'log_subject'),
    [('_log_sync_result', 'assignment'), ('_log_unassignment_sync_result', 'unassignment')],
)
def test_authenticator_map_sync_logs_missing_service_response(caplog, callback_name, log_subject):
    from aap_gateway_api.authentication.reconcile import ReconcileUser

    callback = getattr(ReconcileUser, callback_name)
    with caplog.at_level(logging.WARNING, logger='aap.gateway.authentication.reconcile'):
        callback(SimpleNamespace(api_slug='controller'), None)

    assert f'Authenticator-map {log_subject} sync to controller did not receive a response' in caplog.messages


@pytest.mark.django_db
def test_gateway_uses_syncing_authenticator_map_reconciler():
    """Gateway config selects its reconciler instead of DAB's no-sync default."""
    from aap_gateway_api.authentication.reconcile import ReconcileUser

    assert load_reconcile_user_class() is ReconcileUser
