import logging
from collections import OrderedDict

from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.authentication.models.authenticator import Authenticator
from ansible_base.resource_registry.models import Resource, ResourceType, service_id
from ansible_base.resource_registry.rest_client import ResourceRequestBody
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from requests.exceptions import HTTPError

from aap_gateway_api.models import DefaultServiceType, MigratedAuthenticatorMetadata, MigratedUserMetadata, ServiceAPIRoute, ServiceType
from aap_gateway_api.utils.resources_client import GWResourceAPIClient

logger = logging.getLogger('aap_gateway_api.management.commands.migrate_service_data')
User = get_user_model()


class Command(BaseCommand):
    help = """Migrate Organizations and teams from existing AAP installations into the gateway.

    There is no option to control merging of users, because users are never migrated.
    The exception is that the provided --username, which will be merged."""

    def add_arguments(self, parser):
        services = ServiceAPIRoute.objects.exclude(service_cluster__service_type__name=DefaultServiceType.GATEWAY.value).values_list("api_slug", flat=True)

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
            default=True,
        )

    def handle(self, *args, **options):
        self.service_slug = options["api_slug"]
        merge_teams = options["merge_teams"]
        merge_organizations = options["merge_organizations"]
        username = options["username"]

        # The order here matters. Organizations need to be migrated first.
        self.resource_types_to_migrate = OrderedDict()

        self.resource_types_to_migrate["shared.organization"] = {
            "merge": merge_organizations,
            "type": ResourceType.objects.get(name="shared.organization"),
            "unique_fields": [
                "name",
            ],
        }
        self.resource_types_to_migrate["shared.team"] = {
            "merge": merge_teams,
            "type": ResourceType.objects.get(name="shared.team"),
            "unique_fields": [
                "name",
                "organization",
            ],
        }
        self.resource_types_to_migrate["shared.user"] = {
            "merge": True,  # only indicates we merge the admin user
            "type": ResourceType.objects.get(name="shared.user"),
            "unique_fields": [
                "username",
            ],
        }

        try:
            service_api = ServiceAPIRoute.objects.get(api_slug=self.service_slug)
        except ServiceAPIRoute.DoesNotExist:
            raise CommandError(f"Service with API slug {self.service_slug} does not exist.")

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"Username {username} does not exist")

        # TODO: switch user out for _system. Need to get more fine grained permissions in resources
        # api merged first.
        self.client = GWResourceAPIClient(service_api, raise_if_bad_request=True, user=user)

        try:
            self.stdout.write("Starting migration")

            self.stdout.write("Getting service metadata")
            service_metadata = self.client.get_service_metadata().json()

            self.upstream_service_id = service_metadata["service_id"]
            # Preserve coersion of awx -> controller and galaxy -> hub
            if service_metadata["service_type"].casefold() == "awx".casefold():
                service_type_name = DefaultServiceType.CONTROLLER.value
            elif service_metadata["service_type"].casefold() == "galaxy".casefold():
                service_type_name = DefaultServiceType.HUB.value
            else:
                service_type_name = service_metadata["service_type"]
            upstream_service_type = ServiceType.objects.filter(name=service_type_name).first()
            if upstream_service_type is None:
                raise CommandError(f"Migrations are not allowed for services of type {service_metadata['service_type']}")

            if upstream_service_type.name != service_api.service_cluster.service_type.name:
                raise CommandError(
                    f"Service type mismatch: Service {self.service_slug} is configured as type {service_api.service_cluster.service_type.name},"
                    f" but the server is reporting type {upstream_service_type.name}"
                )

            service_api.service_cluster.service_id = self.upstream_service_id
            service_api.service_cluster.save()

            self.stdout.write(
                f"Migrating {', '.join(self.resource_types_to_migrate.keys())} from {upstream_service_type}, id: {self.upstream_service_id} into Gateway"
            )

            self.migrate_controller_admin()

            for r_type in self.resource_types_to_migrate.keys():
                self.migrate_resource(r_type)

            self.stdout.write("Done")

        except HTTPError as e:
            raise CommandError("Bad API request: " + str(e))

    def get_new_resource_name(self, name, unique_filter_kwargs: dict, LocalResourceModel, resource_type_name_field):
        """
        Find a new name for the resource that does not violate any uniqueness constraints.
        """
        original_name = f'{self.service_slug}_{name}'
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
                sso_server=social["sso_server"].rstrip("/") if social["sso_server"] else None,
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

            AuthenticatorUser.objects.create(provider=authenticator_meta.authenticator, uid=initial_data["username"], user=user.content_object)

    def migrate_controller_admin(self):
        service_type = self.client.service.service_cluster.service_type

        if str(service_type) == "controller" and not self.client.user.has_usable_password():
            authenticator, _ = Authenticator.objects.get_or_create(
                type="aap_gateway_api.authentication.authenticator_plugins.controller_admin",
                defaults={"enabled": True, "name": "controller admin password"},
            )

            if not self.client.user.authenticator_users.filter(provider=authenticator).exists():
                AuthenticatorUser.objects.create(
                    user=self.client.user,
                    provider=authenticator,
                    uid=self.client.user.username,
                )

    def update_resource_data(self, resource_type_name, original_resource_data):
        """
        Used for producing updated resource data for resource that failed validation.
        """
        # if the resource is a user and there is only one validation error for email field, we can remove the field
        if resource_type_name == "shared.user" and "email" in original_resource_data.errors and len(original_resource_data.errors.keys()) == 1:
            self.stderr.write(f"Removing invalid email address \'{original_resource_data.data['email']}\' for user: {original_resource_data.data['username']}")
            # we want to update the email to empty string
            updated_resource_data = original_resource_data.data
            updated_resource_data["email"] = ""
            return updated_resource_data

    def migrate_resource(self, resource_type_name):
        """
        Get a list of resources from the upstream service and add them to the gateway.
        """
        self.stdout.write(f"Migrating data for {resource_type_name}")

        resource_type = self.resource_types_to_migrate[resource_type_name]["type"]
        merge = self.resource_types_to_migrate[resource_type_name]["merge"]
        unique_fields = self.resource_types_to_migrate[resource_type_name]["unique_fields"]

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

        # Following 'while True' loop is used because we are modifying the list as we go through it.
        # By changing the service ID or setting partially migrated, we are removing items from the filter,
        # so this doesn't actually use pagination. It just keeps loading the same filter over and over
        # until nothing is left to migrate.
        while True:
            data = self.client.list_resources(filters=api_call_filters).json()
            self.stdout.write(f"Items remaining: {data['count']}")
            results = data['results']
            # As special case exclude the system user, since Gateway excludes this in its own resources
            if resource_type_name == 'shared.user':
                # TODO: SYSTEM_USERNAME can theoretically vary by service, does this break if it's customized?
                results = [res for res in results if res['name'] != settings.SYSTEM_USERNAME]

            if len(results) == 0:
                self.stdout.write("No more items remaining to migrate.")
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

                if original_resource_data.is_valid(raise_exception=False):
                    original_resource_data = original_resource_data.validated_data
                else:
                    # if the validation failed, attempt to update resource data
                    updated_resource_data = self.update_resource_data(resource_type_name, original_resource_data)
                    if updated_resource_data is not None:
                        # update the original resource data and the resource itself
                        original_resource_data = updated_resource_data
                        resource["resource_data"] = updated_resource_data
                        # might need to figure out if the resource["resource_data"] is the only one we need to update
                    else:
                        # updating didn't produce valid data for the resource, hence this resource is invalid
                        self.stderr.write(
                            f"Resource with id '{resource_ansible_id}' of type '{resource_type_name}'"
                            f" failed validation with errors: {str(original_resource_data.errors)}"
                        )
                        # Raising exception here to stop migration to draw attention to existence of invalid resources.
                        raise RuntimeError("Stopping migration of resources because invalid, non-correctable, resource(s) were encountered.")

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

                create_gateway_resource = True
                resource_creation_kwargs = {"ansible_id": resource_ansible_id}
                # User are treated specially, we partially migrate
                user_partial_migration = bool(resource_type_name == "shared.user" and resource["name"] != self.client.user.username)
                if user_partial_migration:
                    # We do not update the service_id of a user, so we mark is_partially_migrated to exclude it from next loop
                    updated_service_resource = {"is_partially_migrated": True}
                    # The resource created in Gateway needs to show as unmigrated by having the original service_id
                    resource_creation_kwargs["service_id"] = self.upstream_service_id
                    merge_item = False
                else:
                    # This is the request object we send to the upstream service to update the resource.
                    # At the very least, this will update the 'service_id'.
                    updated_service_resource = {"service_id": str(service_id())}
                    merge_item = merge

                if existing_resource:
                    if str(existing_resource.ansible_id) == resource_ansible_id:
                        # NOTE: the JWT auth classes create some items with correct ansible_id
                        # but without the service_id fully set, so this will reconcile those cases
                        create_gateway_resource = False
                        updated_service_resource["service_id"] = existing_resource.service_id
                        local_data = resource_type.serializer_class(existing_resource.content_object).data
                        if resource.get("resource_data", {}) == local_data:
                            logger.info(f"Correcting service_id of {resource_type.name} with name {resource['name']}.")
                        else:
                            updated_service_resource["resource_data"] = local_data
                            logger.warning(f"Updating already-merged {resource_type.name} with name {resource['name']}.")

                    if merge_item:
                        # Set upstream metadata and ansible_id to be same as gateway's
                        # Don't update anything on the gateway
                        create_gateway_resource = False
                        updated_service_resource["ansible_id"] = existing_resource.ansible_id
                        updated_service_resource["resource_data"] = resource_type.serializer_class(existing_resource.content_object).data
                        logger.warning(f"Merging {resource_type.name} with conflicting name {resource['name']}.")
                    elif str(existing_resource.ansible_id) != resource_ansible_id:
                        # We are not correcting the service-side of the same resource.
                        #
                        # Change the name of the resource and update it on the upstream service
                        # Create a new resource in the gateway with the updated name
                        new_name = self.get_new_resource_name(resource["name"], unique_filter_kwargs, LocalResourceModel, resource_type_name_field)
                        resource["resource_data"][resource_type_name_field] = new_name
                        updated_service_resource["resource_data"] = resource["resource_data"]
                        logger.warning(f"Creating new {resource_type.name} with new name {resource['name']}.")

                # Run this as a transaction so that if the REST call to update the resource on the service fails
                # we also rollback any database changes that were made on the gateway.
                with transaction.atomic():
                    if create_gateway_resource:
                        gw_resource = Resource.create_resource(resource_type, resource["resource_data"], **resource_creation_kwargs)
                    else:
                        gw_resource = existing_resource

                    # Connect legacy authentication for users, but do not connect any for the superuser
                    if user_partial_migration:
                        # Create the migration entry only if we are actually creating a gateway
                        # resource.  If we aren't we're updating an already existing user on
                        # the service.
                        if create_gateway_resource:
                            self.create_user_migration_entry(gw_resource, original_resource_data, resource["additional_data"])

                    self.client.update_resource(resource_ansible_id, ResourceRequestBody(**updated_service_resource), partial=True)
