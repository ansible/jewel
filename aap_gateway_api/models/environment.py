from rest_framework.reverse import reverse_lazy

from aap_gateway_api.models.common import NamedCommonModel


class Environment(NamedCommonModel):
    class Meta:
        app_label = 'aap_gateway_api'
        ordering = ('name',)

    # Return NamedCommonModel summary and related fields
    def get_summary_fields(self):
        return {}

    # What items are related to this object
    def related_fields(self, request):
        res = super().related_fields(request)
        res['organizations'] = reverse_lazy('environment-organizations', kwargs={'pk': self.pk}, request=request)
        res['services'] = reverse_lazy('environment-services', kwargs={'pk': self.pk}, request=request)
        return res
