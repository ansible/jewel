from aap_gateway_api.models.common import NamedCommonModel


class Environment(NamedCommonModel):
    class Meta:
        app_label = 'aap_gateway_api'
        ordering = ('name',)

    reverse_foreign_key_fields = ['organizations', 'services']
