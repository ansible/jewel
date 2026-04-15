import copy
import logging
from typing import Optional

from ansible_base.feature_flags.models import AAPFlag
from ansible_base.rbac.models import DABPermission, RoleDefinition
from ansible_base.resource_registry.registry import ParentResource, ResourceConfig, ServiceAPIConfig, SharedResource
from ansible_base.resource_registry.shared_types import FeatureFlagType, OrganizationType, RoleDefinitionType, TeamType, UserType
from ansible_base.resource_registry.utils.resource_type_processor import ResourceTypeProcessor
from crum import get_current_user
from django.db.models import Model
from rest_framework import serializers
from rest_framework.serializers import ValidationError

from aap_gateway_api import models
from aap_gateway_api.utils.models import get_model_lookup_keys

logger = logging.getLogger('aap.gateway.resource_api')

_GATEWAY_SERIALIZER_MAP = None


def _get_gateway_serializer_map():
    """Lazy-load the model → serializer mapping to avoid
    circular imports at module level."""
    global _GATEWAY_SERIALIZER_MAP
    if _GATEWAY_SERIALIZER_MAP is None:
        from aap_gateway_api.serializers.organization import OrganizationSerializer
        from aap_gateway_api.serializers.team import TeamSerializer
        from aap_gateway_api.serializers.user import UserSerializer

        _GATEWAY_SERIALIZER_MAP = {
            models.User: UserSerializer,
            models.Organization: OrganizationSerializer,
            models.Team: TeamSerializer,
        }
    return _GATEWAY_SERIALIZER_MAP


class _SyncRequest:
    """Minimal request-like object that carries just enough
    context for Gateway serializers during resource-registry
    operations."""

    def __init__(self, user):
        self.user = user
        self.method = 'PATCH'
        self.data = {}


class GetOrCreateProcessor(ResourceTypeProcessor):
    def _validate_via_gateway_serializer(self, validated_data):
        """Run validated_data through the Gateway serializer for
        this model so that *all* its validation rules apply to
        reverse-sync payloads (email restrictions, field
        permissions, etc.).

        Fields that fail validation are silently stripped from
        validated_data and logged so the rest of the sync still
        succeeds.
        """
        if self.instance.pk is None:
            return

        try:
            ser_cls = _get_gateway_serializer_map().get(self.instance.__class__)
            if ser_cls is None:
                return

            user = get_current_user()
            request = _SyncRequest(user) if user else None

            ser = ser_cls(
                instance=self.instance,
                data=validated_data,
                partial=True,
                context={
                    'request': request,
                    'view': None,
                },
            )
            if ser.is_valid():
                return
        except Exception:
            logger.exception(
                "Unexpected error validating resource-registry payload for %s pk=%s; allowing update to proceed unfiltered.",
                self.instance.__class__.__name__,
                self.instance.pk,
            )
            return

        for field_name, errors in ser.errors.items():
            if field_name in validated_data:
                logger.warning(
                    "Blocked field '%s' on %s (pk=%s) via resource registry.  Requesting user: %s.  Errors: %s",
                    field_name,
                    self.instance.__class__.__name__,
                    self.instance.pk,
                    user,
                    errors,
                )
                del validated_data[field_name]

    def save(self, validated_data, is_new=False):
        """
        Save the resource instance using the provided
        validated_data.

        If ``is_new`` is True (POST) this tries to find an
        existing object by unique fields; if found it updates,
        otherwise creates.

        If ``is_new`` is False (PUT/PATCH) it sets the fields
        directly.

        In both update paths the data is first validated through
        the Gateway's own serializer so that all business rules
        (email restrictions, field permissions, etc.) are
        enforced even though the request arrived via the resource
        registry rather than the normal API.
        """
        if is_new:
            lookup_fields = get_model_lookup_keys(self.instance.__class__)

            validated_data = copy.deepcopy(validated_data)
            lookup_kwargs = {k: validated_data.pop(k) for k in lookup_fields if k in validated_data}

            existing = self.instance.__class__.objects.filter(**lookup_kwargs).first()
            if existing:
                self.instance = existing
                self._validate_via_gateway_serializer(validated_data)
                changed = any(not hasattr(self.instance, k) or getattr(self.instance, k) != val for k, val in validated_data.items())
                for k, val in validated_data.items():
                    setattr(self.instance, k, val)
                self.instance.save()
                return (changed, self.instance)
            else:
                self.instance, _ = self.instance.__class__.objects.update_or_create(
                    **lookup_kwargs,
                    defaults=validated_data,
                )
                return (True, self.instance)

        self._validate_via_gateway_serializer(validated_data)

        changed_fields = []
        for k, val in validated_data.items():
            if not hasattr(self.instance, k) or getattr(self.instance, k) != val:
                setattr(self.instance, k, val)
                changed_fields.append(k)

        if changed_fields:
            self.instance.save(update_fields=changed_fields)
        return (bool(changed_fields), self.instance)


class GatewayRoleDefinitionProcessor(GetOrCreateProcessor):
    """Gateway is unique because it knows of permissions for all services, and other services do not

    This processes saving of permissions based on the assumption that the client is 1 service.
    A service should have no knowledge of any other non-shared service,
    and if the request claims to, it should be rejected.
    """

    def update_instance_permissions(self, new_perms: list[Model], existing_perms: Optional[list[Model]]):
        # Collect the service slugs that this update will affect permissions for
        new_services = {perm.content_type.service for perm in new_perms}

        if (len(new_services) == 2 and 'shared' in new_services) or len(new_services) == 1:
            # Find existing permissions that impact these services
            if existing_perms is None:
                # For new objects we add all permissions
                self.instance.permissions.add(*new_perms)
            else:
                current_relevant_set = {perm for perm in existing_perms if perm.content_type.service in new_services}
                new_perms_set = set(new_perms)
                to_remove = current_relevant_set - new_perms_set
                to_add = new_perms_set - current_relevant_set

                if to_add:
                    self.instance.permissions.add(*to_add)
                if to_remove:
                    self.instance.permissions.remove(*to_remove)
        else:
            # Unexpected, throw an error
            raise ValidationError('Not expected to set permissions for more than 1 non-shared service')

    def save(self, validated_data, is_new=False):
        new_perms = None  # many-to-many field
        super_validated_data = {}
        for k, val in validated_data.items():
            if k == 'permissions':
                new_perms = val
            else:
                super_validated_data[k] = val

        existing_perms = None
        if new_perms and self.instance.pk:
            existing_perms = list(self.instance.permissions.all())

        (changed, _) = super().save(super_validated_data, is_new=is_new)

        # partial updates might not change permissions
        if new_perms:
            self.update_instance_permissions(new_perms=new_perms, existing_perms=existing_perms)
            changed = True

        return (changed, self.instance)


class StrictPermissionSlugListField(serializers.ListField):
    """Unlike the permissions field in the base serializer in other services, this errors if a permission does not exist"""

    child = serializers.CharField()

    def to_internal_value(self, data):
        slugs = super().to_internal_value(data)
        perms_qs = DABPermission.objects.filter(api_slug__in=slugs)
        perms_by_slug = {p.api_slug: p for p in perms_qs}

        missing = [slug for slug in slugs if slug not in perms_by_slug]
        if missing:
            raise DABPermission.DoesNotExist(f"Permissions not found for api_slug(s): {', '.join(missing)}")

        return [perms_by_slug[slug] for slug in slugs]

    def to_representation(self, value):
        return [perm.api_slug for perm in value.all() if perm is not None]


class GatewayRoleDefinitionType(RoleDefinitionType):
    permissions = StrictPermissionSlugListField()


class APIConfig(ServiceAPIConfig):
    service_type = "aap"
    custom_resource_processors = {
        "shared.organization": GetOrCreateProcessor,
        "shared.team": GetOrCreateProcessor,
        "shared.user": GetOrCreateProcessor,
        "shared.roledefinition": GatewayRoleDefinitionProcessor,
        "shared.aapflag": GetOrCreateProcessor,
    }


RESOURCE_LIST = (
    ResourceConfig(
        models.Organization,
        shared_resource=SharedResource(serializer=OrganizationType, is_provider=True),
    ),
    ResourceConfig(
        models.User,
        shared_resource=SharedResource(serializer=UserType, is_provider=True),
        name_field="username",
    ),
    ResourceConfig(
        models.Team,
        shared_resource=SharedResource(serializer=TeamType, is_provider=True),
        parent_resources=[ParentResource(model=models.Organization, field_name="organization")],
    ),
    ResourceConfig(
        RoleDefinition,
        shared_resource=SharedResource(serializer=GatewayRoleDefinitionType, is_provider=True),
    ),
    ResourceConfig(
        AAPFlag,
        shared_resource=SharedResource(serializer=FeatureFlagType, is_provider=True),
    ),
)
