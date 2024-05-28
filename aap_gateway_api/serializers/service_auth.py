from ansible_base.lib.serializers.common import CommonModelSerializer
from rest_framework import serializers

from aap_gateway_api.models import ServiceKey


class ServiceKeySerializer(CommonModelSerializer):
    secret_length = serializers.IntegerField(min_value=64, max_value=512, default=64, write_only=True)
    mark_previous_inactive = serializers.BooleanField(write_only=True, required=True)
    algorithm = serializers.ChoiceField(
        choices=ServiceKey.JWTAlgorithm.choices,
        default=ServiceKey.JWTAlgorithm.HS256,
    )

    class Meta:
        model = ServiceKey
        fields = CommonModelSerializer.Meta.fields + [
            "service_cluster",
            "is_active",
            "algorithm",
            "secret_length",
            "mark_previous_inactive",
            "secret",
        ]

    def create(self, validated_data):
        service_cluster = validated_data["service_cluster"]

        obj = service_cluster.generate_key(
            algorithm=validated_data.get("algorithm"),
            secret_length=validated_data["secret_length"],
            mark_previous_inactive=validated_data["mark_previous_inactive"],
        )

        return obj
