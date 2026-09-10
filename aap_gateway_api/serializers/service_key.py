from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from ansible_base.lib.serializers.mixins import CleanTextMixin
from django.conf import settings
from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers
from rest_framework.serializers import ValidationError

from aap_gateway_api.models import ServiceKey


class ServiceKeySerializerRead(CleanTextMixin, NamedCommonModelSerializer):
    secret_length = serializers.IntegerField(
        read_only=True,
        help_text="DEPRECATED: This field is no longer editable",
    )
    mark_previous_inactive = serializers.BooleanField(
        read_only=True,
        help_text="DEPRECATED: This field is no longer editable",
    )

    class Meta:
        model = ServiceKey
        fields = NamedCommonModelSerializer.Meta.fields + [
            "service_cluster",
            "is_active",
            "algorithm",
            "secret_length",
            "mark_previous_inactive",
            "secret",
        ]

    def create(self, validated_data):
        raise ValidationError("POST method has been removed from this endpoint.")

    def validate_is_active(self, value):
        # You can always disable a key
        if value is False:
            return value

        # validate() blocks creation, so instance should always exist here
        if not self.instance:
            raise ValidationError("Internal error: we should have had an instance object to validate against.")

        # If we're not changing the field we can return the existing value.
        if value == getattr(self.instance, "is_active", None):
            return value

        active_keys = ServiceKey.objects.filter(service_cluster=getattr(self.instance, "service_cluster", None), is_active=True).count()

        if active_keys >= settings.MAX_ACTIVE_KEYS_PER_SERVICE:
            raise ValidationError("Cannot activate this key, maximum number of active keys reached for this service cluster.")

        return value


@extend_schema_serializer(
    deprecate_fields=["service_cluster", "algorithm", "secret_length", "mark_previous_inactive", "secret"],
)
class ServiceKeySerializerWrite(ServiceKeySerializerRead):
    class Meta(ServiceKeySerializerRead.Meta):
        ref_name = "ServiceKey"
