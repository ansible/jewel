from aap_gateway_api.models import Authenticator
from aap_gateway_api.serializers.common import NamedCommonModelSerializer


class AuthenticatorSerializer(NamedCommonModelSerializer):
    reverse_url_name = 'authenticator-detail'

    class Meta:
        model = Authenticator
        fields = NamedCommonModelSerializer.Meta.fields + [x.name for x in Authenticator._meta.concrete_fields]
