from ansible_base.feature_flags.models import AAPFlag
from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from flags.state import flag_state
from rest_framework import serializers


class FeatureFlagSerializer(NamedCommonModelSerializer):
    """Serialize list of feature flags"""

    state = serializers.SerializerMethodField()

    class Meta:
        model = AAPFlag
        fields = NamedCommonModelSerializer.Meta.fields + [x.name for x in AAPFlag._meta.concrete_fields] + ['state']
        read_only_fields = ["name", "condition", "required", "support_level", "visibility", "toggle_type", "description", "labels", "ui_name", "support_url"]

    def get_state(self, instance):
        return flag_state(instance.name)

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        return ret


class FeatureFlagPatchSerializer(NamedCommonModelSerializer):
    class Meta:
        model = AAPFlag
        fields = ['value']
