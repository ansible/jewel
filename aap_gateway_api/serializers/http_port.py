from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from django.utils.translation import gettext as _
from rest_framework import serializers

from aap_gateway_api.models import HTTPPort


class HTTPPortSerializer(NamedCommonModelSerializer):
    class Meta:
        model = HTTPPort
        fields = NamedCommonModelSerializer.Meta.fields + ['number', 'use_https', 'is_api_port']

    def validate_is_api_port(self, value):
        """
        Prevent changing is_api_port from True to False, which would cause the
        proxy to become inoperable. This is normally prevented by DisallowWriteFromProxy
        but is added here as another layer of protection in case someone manages to directly
        access Gateway.
        """
        if self.instance and self.instance.is_api_port and not value:
            raise serializers.ValidationError(_("The API port cannot be changed to a non-API port"))
        return value
