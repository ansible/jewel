from ansible_base.lib.abstract_models.common import NamedCommonModel


class Environment(NamedCommonModel):
    class Meta:
        app_label = 'aap_gateway_api'
        ordering = ('name',)

    reverse_foreign_key_fields = ['organizations']
