import logging
from collections import OrderedDict

from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.resource_registry.models import Resource, ResourceType, service_id
from ansible_base.resource_registry.rest_client import ResourceRequestBody
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from requests.exceptions import HTTPError

from aap_gateway_api.models import MigratedAuthenticatorMetadata, MigratedUserMetadata, ServiceAPIRoute, ServiceCluster
from aap_gateway_api.utils.resources_client import GWResourceAPIClient

logger = logging.getLogger('aap_gateway_api.management.commands.migrate_service_data')
User = get_user_model()


service_type_map = {
    # "aap": ServiceCluster.ServiceType.GATEWAY,
    "awx": ServiceCluster.ServiceType.CONTROLLER,
    "galaxy": ServiceCluster.ServiceType.HUB,
    "eda": ServiceCluster.ServiceType.EDA,
}


class Command(BaseCommand):
    help = "Migrate Organizations and teams from existing AAP installations into the gateway."

    def add_arguments(self, parser):
        services = ServiceAPIRoute.objects.exclude(service_cluster__service_type=ServiceCluster.ServiceType.GATEWAY).values_list("api_slug", flat=True)

        parser.add_argument("--api-slug", type=str, help="API slug for the ServiceAPIRoute that you wish to migrate.", choices=services, required=True)
        parser.add_argument("--username", type=str, help="Username for the gateway user to use on the request. Must be an admin user.", required=True)
        parser.add_argument(
            "--merge-teams",
            type=bool,
            help=(
                "If true, teams with the same names on different services will be combined. NOTE: this can potentially lead to"
                " escalation of privileges, as users who are in Team A in service A, will also end up in Team A on service B, even "
                "if they weren't before."
            ),
            default=False,
        )
        parser.add_argument(
            "--merge-organizations",
            type=bool,
            help=(
                "If true, organizations with the same names on different services will be combined. NOTE: this can potentially lead to"
                " escalation of privileges, as users and resources who are in Org A in service A, will also end up in Org A on service "
                "B, even if they weren't before."
            ),
            default=False,
        )
        parser.add_argument(
            "--merge-users",
            type=bool,
            help=("If true, users with the same usernames on different services will be combined."),
            default=True,
        )

    def handle(self, *args, **options):
        self.service_slug = options["api_slug"]
        merge_teams = options["merge_teams"]
        merge_organizations = options["merge_organizations"]
        merge_users = options["merge_users"]
        username = options["username"]

        # The order here matters. Organizations need to be migrated first.
        self.resource_types_to_migrate = OrderedDict()

        self.resource_types_to_migrate["shared.organization"] = {
            "merge": merge_organizations,
            "type": ResourceType.objects.get(name="shared.organization"),
            "unique_fields": [
                "name",
            ],
            "perform_partial_migration": False,
        }
        self.resource_types_to_migrate["shared.team"] = {
            "merge": merge_teams,
            "type": ResourceType.objects.get(name="shared.team"),
            "unique_fields": [
                "name",
                "organization",
            ],
            "perform_partial_migration": False,
        }
        self.resource_types_to_migrate["shared.user"] = {
            "merge": merge_users,
            "type": ResourceType.objects.get(name="shared.user"),
            "unique_fields": [
                "username",
            ],
            "perform_partial_migration": True,
        }

        try:
            service_api = ServiceAPIRoute.objects.get(api_slug=self.service_slug)
        except ServiceAPIRoute.DoesNotExist:
            raise CommandError(f"Service with API slug {self.service_slug} does not exist.")

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"Username {user} does not exist")

        # TODO: switch user out for _system. Need to get more fine grained permissions in resources
        # api merged first.
        self.client = GWResourceAPIClient(service_api, raise_if_bad_request=True, user=user)

        try:
            self.stdout.write("Starting migration")

            self.stdout.write("Getting service metadata")
            service_metadata = self.client.get_service_metadata().json()

            self.upstream_service_id = service_metadata["service_id"]
            upstream_service_type = service_type_map.get(service_metadata["service_type"])
            if upstream_service_type is None:
                raise CommandError(f"Migrations are not allow for services of type {upstream_service_type}")

            if upstream_service_type != service_api.service_cluster.service_type:
                raise CommandError(
                    f"Service type mismatch: Service {self.service_slug} is configured as type {service_api.service_cluster.service_type},"
                    f" but the server is reporting type {upstream_service_type}"
                )

            service_api.service_cluster.service_id = self.upstream_service_id
            service_api.service_cluster.save()

            self.stdout.write(
                f"Migrating {', '.join(self.resource_types_to_migrate.keys())} from {upstream_service_type}, id: {self.upstream_service_id} into Gateway"
            )
            for r_type in self.resource_types_to_migrate.keys():
                self.migrate_resource(r_type)

            self.stdout.write("Done")

        except HTTPError as e:
            raise CommandError("Bad API request: " + str(e))

    def get_new_resource_name(self, name, unique_filter_kwargs: dict, LocalResourceModel, resource_type_name_field):
        """
        Find a new name for the resource that does not violate any uniqueness constraints.
        """
        original_name = f'{self.service_slug}:{name}'
        name = original_name

        filter_kwargs = unique_filter_kwargs.copy()
        filter_kwargs[resource_type_name_field] = name

        counter = 1
        while LocalResourceModel.objects.filter(**filter_kwargs).exists():
            name = original_name + str(counter)
            filter_kwargs[resource_type_name_field] = name
            counter += 1

        return name

    def create_user_migration_entry(self, user, initial_data, additional_data):
        service_cluster = self.client.service.service_cluster
        MigratedUserMetadata.objects.create(
            user=user.content_object,
            service=service_cluster,
            original_username=initial_data["username"],
        )

        for social in additional_data["social_auth"]:
            authenticator_meta, _ = MigratedAuthenticatorMetadata.objects.get_or_create(
                type=MigratedAuthenticatorMetadata.LegacyAuthTypes.SSO,
                django_backend=social["backend_type"],
                sso_server=social["sso_server"].rstrip("/"),
                service=service_cluster,
            )

            AuthenticatorUser.objects.create(
                user=user.content_object,
                provider=authenticator_meta.authenticator,
                uid=social["uid"],
            )

        if len(additional_data["social_auth"]) == 0:
            authenticator_meta, _ = MigratedAuthenticatorMetadata.objects.get_or_create(
                type=MigratedAuthenticatorMetadata.LegacyAuthTypes.PASSWORD,
                service=service_cluster,
            )

            AuthenticatorUser.objects.create(
                user=user.content_object,
                provider=authenticator_meta.authenticator,
                uid=initial_data["username"],
            )

    def migrate_resource(self, resource_type_name):
        """
        Get a list of resources from the upstream service and add them to the gateway.
        """
        self.stdout.write("Migrating data for " + resource_type_name)

        resource_type = self.resource_types_to_migrate[resource_type_name]["type"]
        merge = self.resource_types_to_migrate[resource_type_name]["merge"]
        unique_fields = self.resource_types_to_migrate[resource_type_name]["unique_fields"]

        # Perform a partial migration if it is enable for the resource type and merge is set
        # to false. This will result in the resource being copied to Gateway, but the service_id
        # being kept to the original service's.
        perform_partial_migration = self.resource_types_to_migrate[resource_type_name]["perform_partial_migration"] and not merge

        resource_serializer = resource_type.serializer_class
        resource_type_name_field = resource_type.get_resource_config().name_field

        LocalResourceModel = resource_type.content_type.model_class()

        # Each resource that gets updated in the gateway will change the service ID, and will cause
        # the migrated resources to be filtered out of the server response, so we don't need to
        # deal with pagination here. We just keep calling the list view until the filter returns
        # no items.
        api_call_filters = {
            "service_id": self.upstream_service_id,
            "is_partially_migrated": "false",
            "content_type__resource_type__name": resource_type_name,
        }

        while True:
            data = self.client.list_resources(filters=api_call_filters).json()
            self.stdout.write(f"Items remaining: {data['count']}")
            results = data['results']
            # As special case exclude the system user, since Gateway excludes this in its own resources
            if resource_type_name == 'shared.user':
                results = [res for res in results if res['name'] != settings.SYSTEM_USERNAME]
            if len(results) == 0:
                break

            for resource_list in results:
                resource_type_name = resource_list["resource_type"]
                resource_ansible_id = resource_list["ansible_id"]

                # TODO: Should we add the resource_data to the list view serializer so that we
                # don't have to make a GET request for every single resource?
                # get the resource details
                resource = self.client.get_resource(resource_ansible_id).json()

                # de-serialize the data so that we can decode ansible_ids into foreign key values
                original_resource_data = resource_serializer(data=resource["resource_data"])
                original_resource_data.is_valid(raise_exception=True)
                original_resource_data = original_resource_data.validated_data

                unique_filter_kwargs = {}
                for field_name in unique_fields:
                    unique_filter_kwargs[field_name] = original_resource_data[field_name]

                try:
                    existing_resource = LocalResourceModel.objects.select_related("resource").get(**unique_filter_kwargs).resource
                except LocalResourceModel.DoesNotExist:
                    existing_resource = None

                # Now that we have all of the data from the service we need to do one of three things:
                # - If the resource exists in the gateway and merge is set to true: Don't change anything in
                #   the gateway. Set the "ansible_id" and "service_id" on the resource in the service to
                #   match the gateway's value. This indicates that the resource is managed by the gateway
                #   and that the it is the same resource as the one that already exists in Gateway
                # - If the resource exists in the gateway and merge is set to false: Create a new resource
                #   in Gateway with a name that doesn't conflict with the existing resource in the service
                #   using the "ansible_id" provided by the service. Rename the existing resource on the
                #   service and set the "service_id" to the gateway's ID.
                # - If the resource doesn't exist in Gateway: Create a new resource in Gateway using the
                #   data from the resource in the service, including the "ansible_id". Set the "service_id"
                #   of the resource in the service to match the gateway's ID.
                #
                # Note that in all cases we're setting the "service_id" on the resource in the service to
                # match the gateway's ID. This indicates to the service and to the gateway that the resource
                # is now managed externally by the gateway.

                # This is the request object we send to the upstream service to update the resource.
                # At the very least, this will update the 'service_id'.
                updated_service_resource = {"service_id": str(service_id())}
                create_gateway_resource = True

                if existing_resource:
                    if str(existing_resource.ansible_id) == resource_ansible_id:
                        # NOTE: the JWT auth classes create some items with correct ansible_id
                        # but without the service_id fully set, so this will reconcile those cases
                        create_gateway_resource = False
                        updated_service_resource["ansible_id"] = existing_resource.ansible_id
                        local_data = resource_type.serializer_class(existing_resource.content_object).data
                        if resource.get("resource_data", {}) == local_data:
                            logger.info(f"Correcting service_id of {resource_type} with name {resource['name']}.")
                        else:
                            updated_service_resource["resource_data"] = local_data
                            logger.warning(f"Updating already-merged {resource_type} with name {resource['name']}.")
                    if merge:
                        # Set upstream metadata and ansible_id to be same as gateway's
                        # Don't update anything on the gateway
                        create_gateway_resource = False
                        updated_service_resource["ansible_id"] = existing_resource.ansible_id
                        updated_service_resource["resource_data"] = resource_type.serializer_class(existing_resource.content_object).data
                        logger.warning(f"Merging {resource_type} with conflicting name {resource['name']}.")
                    else:
                        # Change the name of the resource and update it on the upstream service
                        # Create a new resource in the gateway with the updated name
                        new_name = self.get_new_resource_name(resource["name"], unique_filter_kwargs, LocalResourceModel, resource_type_name_field)
                        resource["resource_data"][resource_type_name_field] = new_name
                        updated_service_resource["resource_data"] = resource["resource_data"]
                        logger.warning(f"Creating new {resource_type} with new name {resource['name']}.")

                # Run this as a transaction so that if the REST call to update the resource on the service fails
                # we also rollback any database changes that were made on the gateway.
                with transaction.atomic():
                    if create_gateway_resource:
                        id_kwargs = {"ansible_id": resource_ansible_id}

                        if perform_partial_migration:
                            id_kwargs["service_id"] = self.upstream_service_id

                        gw_resource = Resource.create_resource(resource_type, resource["resource_data"], **id_kwargs)
                    else:
                        gw_resource = existing_resource

                    if resource_type_name == "shared.user":
                        self.create_user_migration_entry(gw_resource, original_resource_data, resource["additional_data"])

                    if perform_partial_migration:
                        # If we're doing a partial migration, just set the "is_partially_migrated" flag to true, and don't update
                        # anything on the service. By not updating the service ID, we'll prevent this resource from getting synced
                        # to other services until it has been fully migrated. The "is_partially_migrated" flag will allow this
                        # command to remain idempotent without having to iterate through all of the resources in the system.
                        self.client.update_resource(resource_ansible_id, ResourceRequestBody(is_partially_migrated=True), partial=True)
                    else:
                        self.client.update_resource(resource_ansible_id, ResourceRequestBody(**updated_service_resource), partial=True)
