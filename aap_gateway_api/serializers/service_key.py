from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from ansible_base.lib.serializers.mixins import CleanTextMixin
from django.conf import settings
from rest_framework.serializers import ValidationError

from aap_gateway_api.models import ServiceKey


class ServiceKeySerializer(CleanTextMixin, NamedCommonModelSerializer):
    class Meta:
        model = ServiceKey
        fields = NamedCommonModelSerializer.Meta.fields + [
            "service_cluster",
            "is_active",
            "algorithm",
            "secret",
        ]

    def validate(self, attrs):
        if self.instance is None:
            raise ValidationError("Service keys cannot be created through this serializer. Use ServiceCluster.generate_key().")

        return super().validate(attrs)

    def validate_is_active(self, value):
        # You can always disable a key
        if value is False:
            return value

        # If we're not changing the field we can return the existing value.
        if value == self.instance.is_active:
            return value

        active_keys = ServiceKey.objects.filter(service_cluster=self.instance.service_cluster, is_active=True).exclude(pk=self.instance.pk).count()

        if active_keys >= settings.MAX_ACTIVE_KEYS_PER_SERVICE:
            raise ValidationError("Cannot activate this key, maximum number of active keys reached for this service cluster.")

        return value
