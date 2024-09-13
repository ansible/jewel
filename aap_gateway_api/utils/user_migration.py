from ansible_base.resource_registry.models import service_id
from django.db import transaction
from django.utils.translation import gettext as _
from requests.exceptions import HTTPError
from rest_framework.exceptions import ValidationError as DRFValidationError

from aap_gateway_api.models import ServiceAPIRoute
from aap_gateway_api.utils.resources_client import GWResourceAPIClient, ResourceRequestBody


def can_accounts_be_merged(main_account, to_merge):
    if main_account.pk == to_merge.pk:
        DRFValidationError(_("Can't merge an account with itself."))

    main_account_migrated_services = main_account.original_accounts.values_list("service", flat=True)
    for original_account in to_merge.original_accounts.all():
        if original_account.service.pk in main_account_migrated_services:
            raise DRFValidationError(
                _(
                    "Account %(username)s has already been linked to an account from "
                    "%(service_type)s. Only one migrated account from each service may be linked."
                )
                % {"service_type": original_account.service.service_type, "username": main_account.username}
            )

    return True


def migrate_account(user):
    if user.is_migrated:
        return

    with transaction.atomic():
        acct_resource = user.resource
        acct_resource.service_id = service_id()
        acct_resource.is_partially_migrated = False
        acct_resource.save()

        for original in user.original_accounts.all():
            service = ServiceAPIRoute.objects.get(service_cluster=original.service)
            client = GWResourceAPIClient(service=service)

            body = ResourceRequestBody(
                service_id=acct_resource.service_id,
                resource_data={
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "email": user.email,
                },
                is_partially_migrated=False,
            )

            client.update_resource(acct_resource.ansible_id, data=body, partial=True)


def link_account(main_account, to_merge, preserve_authenticators=True, services_to_merge=None):
    if main_account.pk == to_merge.pk:
        return
    with transaction.atomic():
        original_services = []
        if services_to_merge:
            original_services = services_to_merge
        for original in to_merge.original_accounts.all():
            original_services.append(ServiceAPIRoute.objects.get(service_cluster=original.service))
            original.user = main_account
            original.save()

        if preserve_authenticators:
            for auth_user in to_merge.authenticator_users.all():
                auth_user.user = main_account
                auth_user.save()

        to_merge_id = to_merge.resource.ansible_id
        to_merge.delete()

        for service in original_services:
            client = GWResourceAPIClient(service=service, raise_if_bad_request=True)

            # clean up any references to the original account if they got created.
            try:
                client.delete_resource(ansible_id=main_account.resource.ansible_id)
            except HTTPError as e:
                if e.response.status_code != 404:
                    raise

            client.update_resource(
                to_merge_id,
                data=ResourceRequestBody(ansible_id=main_account.resource.ansible_id, resource_data={"username": main_account.username}),
                partial=True,
            )
