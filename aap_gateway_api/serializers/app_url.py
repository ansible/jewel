from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from ansible_base.oauth2_provider.models import OAuth2Application


class AppUrlSerializer(NamedCommonModelSerializer):
    class Meta:
        model = OAuth2Application
        fields = NamedCommonModelSerializer.Meta.fields + [
            'app_url',
        ]
