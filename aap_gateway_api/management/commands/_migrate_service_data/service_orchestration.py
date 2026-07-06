import logging
from typing import Optional, Tuple

from ansible_base.rbac.models import DABContentType, DABPermission
from django.contrib.auth.models import AbstractUser

from aap_gateway_api.models import ServiceAPIRoute, ServiceType
from aap_gateway_api.models.service_type import get_service_type_name
from aap_gateway_api.utils import resources_client


class ServiceOrchestrationMixin:
    """Mixin for per-service migration orchestration and type/permission loading."""

    def load_types_and_permissions(self, service_apis, user):
        failed_services = []
        for service_api in service_apis:
            service_slug = service_api.api_slug
            try:
                client = resources_client.GWResourceAPIClient(service_api, raise_if_bad_request=True, user=user)
                big_page_filter = self.BIG_PAGE_FILTERS

                # Load types into system
                response = client.list_role_types(filters=big_page_filter)

                if response.status_code != 200:
                    raise RuntimeError(f'Service {service_slug} role types gave {response.status_code} code, data: {response.data}')

                data = response.json()

                if data['next']:
                    raise RuntimeError(f'Service {service_slug} has extra pages of types: {data}')

                DABContentType.objects.load_remote_objects(data['results'])

                # Load permissions into system, these reference the types above
                response = client.list_role_permissions(filters=big_page_filter)

                if response.status_code != 200:
                    raise RuntimeError(f'Service {service_slug} permissions gave {response.status_code} code, data: {response.data}')

                data = response.json()

                if data['next']:
                    raise RuntimeError(f'Service {service_slug} has extra pages of types: {data}')

                DABPermission.objects.load_remote_objects(data['results'], update_managed=True)
            except Exception as e:
                self._log(
                    f"Warning: Failed to load types and permissions from {service_slug}: {e}. "
                    f"Role definitions referencing this service's types will not be available until the next successful migration.",
                    logging.WARNING,
                )
                failed_services.append(service_slug)
                continue
        return failed_services

    def _migrate_single_service(
        self,
        service_api: ServiceAPIRoute,
        service_slug: str,
        user: AbstractUser,
    ) -> Tuple[bool, Optional[str]]:
        """Migrate data from a single service."""
        self.client = resources_client.GWResourceAPIClient(service_api, raise_if_bad_request=True, user=user)

        self._log("Starting migration", logging.INFO)

        self._log("Getting service metadata", logging.INFO)
        service_metadata = self.client.get_service_metadata().json()

        self.upstream_service_id = service_metadata["service_id"]
        service_type_name = get_service_type_name(service_metadata["service_type"])

        upstream_service_type = ServiceType.objects.filter(name=service_type_name).first()
        if upstream_service_type is None:
            error_msg = f"Migrations are not allowed for services of type {service_metadata['service_type']}"
            self._log(f"Skipping service {service_slug}: {error_msg}", logging.WARNING)
            return False, error_msg

        if upstream_service_type.name != service_api.service_cluster.service_type.name:
            error_msg = (
                f"Service type mismatch: "
                f"Service is configured as type {service_api.service_cluster.service_type.name}, "
                f"but the server is reporting type {upstream_service_type.name}"
            )
            self._log(f"Skipping service {service_slug}: {error_msg}", logging.WARNING)
            return False, error_msg

        service_api.service_cluster.service_id = self.upstream_service_id
        service_api.service_cluster.save()

        if self._is_service_already_synced():
            self._log(f"Service {service_slug} is already synchronized — skipping resource migration.", logging.INFO)
        else:
            self._log(
                f"Migrating {', '.join(self.resource_types_to_migrate.keys())} from {upstream_service_type}, id: {self.upstream_service_id} into Gateway",
                logging.INFO,
            )

            for r_type in self.resource_types_to_migrate.keys():
                self.migrate_resource(r_type)

        self.migrate_role_assignments(service_slug, service_type_name)

        self._log(f"Completed migration for service: {service_slug}", logging.INFO)
        return True, None
