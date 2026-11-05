from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from ansible_base.lib.serializers.mixins import CleanTextMixin
from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers
from rest_framework.serializers import ValidationError

from aap_gateway_api.models import ServiceCluster, ServiceKey

DEPRECATED_FIELD_HELP_TEXT = "DEPRECATED: This field is no longer editable"


class ServiceKeySerializerRead(CleanTextMixin, NamedCommonModelSerializer):
    service_cluster = serializers.PrimaryKeyRelatedField(
        read_only=True,
        help_text=DEPRECATED_FIELD_HELP_TEXT,
    )
    algorithm = serializers.ChoiceField(
        choices=ServiceKey.JWTAlgorithm.choices,
        read_only=True,
        help_text=DEPRECATED_FIELD_HELP_TEXT,
    )
    secret_length = serializers.IntegerField(
        read_only=True,
        help_text=DEPRECATED_FIELD_HELP_TEXT,
    )
    mark_previous_inactive = serializers.BooleanField(
        read_only=True,
        help_text=DEPRECATED_FIELD_HELP_TEXT,
    )
    secret = serializers.CharField(read_only=True, help_text=DEPRECATED_FIELD_HELP_TEXT)

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


@extend_schema_serializer(
    deprecate_fields=["service_cluster", "algorithm", "secret_length", "mark_previous_inactive", "secret"],
)
class ServiceKeySerializerWrite(ServiceKeySerializerRead):
    # These fields document the deprecated request shape.  The view never uses
    # this serializer at runtime; POST returns 405 and updates use the read
    # serializer, which ignores these fields.
    service_cluster = serializers.PrimaryKeyRelatedField(queryset=ServiceCluster.objects.all(), required=False)
    secret = serializers.CharField(write_only=True, required=False)
    algorithm = serializers.ChoiceField(choices=ServiceKey.JWTAlgorithm.choices, required=False)
    secret_length = serializers.IntegerField(min_value=64, max_value=512, required=False, write_only=True)
    mark_previous_inactive = serializers.BooleanField(required=False, write_only=True)

    class Meta(ServiceKeySerializerRead.Meta):
        ref_name = "ServiceKey"
