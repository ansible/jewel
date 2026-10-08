import logging

from ansible_base.authentication.utils.claims import ReconcileUser as BaseReconcileUser

from aap_gateway_api.utils.resources_client import AllServicesClient

logger = logging.getLogger('aap.gateway.authentication.reconcile')


class ReconcileUser(BaseReconcileUser):
    """Reconcile authenticator-map permissions and batch-publish changes."""

    def apply_permissions(self):
        self._pending_grants = []
        self._pending_removals = []
        super().apply_permissions()
        self._flush_pending_sync()

    def _give_permission(self, role_definition, obj=None):
        assignment = super()._give_permission(role_definition, obj)
        if assignment is not None:
            self._pending_grants.append(assignment)
        return assignment

    def _remove_permission(self, role_definition, obj=None):
        self._pending_removals.append((role_definition, self.user, obj))
        return super()._remove_permission(role_definition, obj)

    def _flush_pending_sync(self):
        if not self._pending_grants and not self._pending_removals:
            return

        client = AllServicesClient(user=self.user, wait_for_response=False)
        if self._pending_grants:
            logger.info('Publishing %s authenticator-map assignments for user %s', len(self._pending_grants), self.user.username)
            client.with_callback(self._log_sync_result).sync_assignments(self._pending_grants)

        if self._pending_removals:
            logger.info('Publishing %s authenticator-map unassignments for user %s', len(self._pending_removals), self.user.username)
            client.with_callback(self._log_unassignment_sync_result).sync_unassignments(self._pending_removals)

    @staticmethod
    def _log_sync_result(service, response):
        ReconcileUser._log_sync_result_for_operation(service, response, 'assignment')

    @staticmethod
    def _log_unassignment_sync_result(service, response):
        ReconcileUser._log_sync_result_for_operation(service, response, 'unassignment')

    @staticmethod
    def _log_sync_result_for_operation(service, response, operation):
        service_name = getattr(service, 'api_slug', None) or str(service.pk)
        if response is None:
            logger.warning('Authenticator-map %s sync to %s did not receive a response', operation, service_name)
        elif not 200 <= response.status_code < 300:
            logger.warning(
                'Authenticator-map %s sync to %s failed: HTTP %s',
                operation,
                service_name,
                response.status_code,
            )
        else:
            logger.info('Authenticator-map %s sync to %s completed: HTTP %s', operation, service_name, response.status_code)
