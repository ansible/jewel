from ansible_base.lib.utils.views.deprecation import DeprecationSerializerMixin
from django.conf import settings


class HideDeprecatedFieldsSerializerMixin(DeprecationSerializerMixin):
    """Omit deprecated response fields when HIDE_V1_API_DEPRECATED_FIELDS is enabled."""

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if getattr(settings, 'HIDE_V1_API_DEPRECATED_FIELDS', False):
            for field_name in self.deprecated_fields:
                data.pop(field_name, None)
        return data
