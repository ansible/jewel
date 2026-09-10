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

    def validate_is_active(self, value):
        # You can always disable a key
        if value is False:
            return value

        if not self.instance:
            raise ValidationError("Internal error: we should have had an instance object to validate against.")

        active_keys = ServiceKey.objects.filter(service_cluster=self.instance.service_cluster, is_active=True).count()

        if active_keys >= settings.MAX_ACTIVE_KEYS_PER_SERVICE:
            raise ValidationError("Cannot activate this key, maximum number of active keys reached for this service cluster.")

        return value
