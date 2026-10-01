import logging

from ansible_base.authentication.utils.claims import ReconcileUser as BaseReconcileUser

from aap_gateway_api.utils.resources_client import AllServicesClient

logger = logging.getLogger('aap.gateway.authentication.reconcile')


class ReconcileUser(BaseReconcileUser):
    """Reconcile authenticator-map permissions and immediately publish new grants."""

    def _give_permission(self, role_definition, obj=None):
        assignment = super()._give_permission(role_definition, obj)
        if assignment:
            logger.info(
                'Publishing authenticator-map assignment for user %s and role %s',
                self.user.username,
                role_definition.name,
            )
            AllServicesClient(user=self.user, wait_for_response=False).with_callback(self._log_sync_result).sync_assignment(assignment)
        return assignment

    @staticmethod
    def _log_sync_result(service, response):
        service_name = getattr(service, 'api_slug', None) or str(service.pk)
        if response is None:
            logger.warning('Authenticator-map assignment sync to %s did not receive a response', service_name)
        elif not 200 <= response.status_code < 300:
            logger.warning(
                'Authenticator-map assignment sync to %s failed: HTTP %s: %s',
                service_name,
                response.status_code,
                response.text,
            )
        else:
            logger.info('Authenticator-map assignment sync to %s completed: HTTP %s', service_name, response.status_code)
