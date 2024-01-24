import collections

from django.utils.translation import gettext_lazy as _
from rest_framework.response import Response
from rest_framework.reverse import reverse

from aap_gateway_api.models import Preference
from aap_gateway_api.serializers import SettingSectionSerializer, SettingSingletonSerializer
from aap_gateway_api.utils import get_preference_sections
from aap_gateway_api.views.api.v1.common import GatewayModelViewSet, ViewWithHeaders


class PreferenceSingletonView(ViewWithHeaders):
    def get_serializer(self, *args, **kwargs):
        return self.serializer

    def options(self, request, category_slug, format=None):
        self.serializer = SettingSingletonSerializer(category_slug)
        return super().options(request, category_slug, format)

    def get(self, request, category_slug, format=None):
        # TODO: Check permissions (should be on the category)
        # self.check_object_permissions(self.request, obj)
        self.serializer = SettingSingletonSerializer(category_slug)
        return Response(self.serializer.to_representation())

    def put(self, request, category_slug, format=None):
        # TODO: Check permissions on the category
        self.serializer = SettingSingletonSerializer(category_slug)
        updated_data = self.serializer.validate_and_save(request.data)
        return Response(updated_data)


PreferenceSection = collections.namedtuple('PreferenceSection', ('url', 'name'))


class PreferenceListViewSet(GatewayModelViewSet):
    model = Preference  # Not exactly, but needed for the view.
    serializer_class = SettingSectionSerializer
    filter_backends = []
    name = _('Setting Categories')
    http_method_names = ['get', 'head']

    def get_queryset(self):
        setting_categories = []
        sections = get_preference_sections()
        # TODO: Make sure we can see the sections
        sorted_sections = ['all']
        sorted_sections.extend(sorted(sections))
        for section in sorted_sections:
            url = reverse('setting-section-list', kwargs={'category_slug': section})
            setting_categories.append(PreferenceSection(url, section))
        return setting_categories
