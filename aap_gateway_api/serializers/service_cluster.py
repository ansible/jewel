from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from rest_framework import serializers

from aap_gateway_api.models import ServiceCluster


class ServiceClusterSerializer(NamedCommonModelSerializer):
    effective_health_check_timeout_seconds = serializers.SerializerMethodField(
        help_text="The effective health check timeout Envoy will use, computed as the maximum of the cluster's "
        "health_check_timeout_seconds, the highest route request_timeout_seconds, and the global request_timeout preference."
    )

    class Meta:
        model = ServiceCluster
        fields = NamedCommonModelSerializer.Meta.fields + [
            'service_type',
            'service_id',
            'auth_type',
            'upstream_hostname',
            'dns_discovery_type',
            'dns_lookup_family',
            'outlier_detection_enabled',
            'outlier_detection_consecutive_5xx',
            'outlier_detection_interval_seconds',
            'outlier_detection_base_ejection_time_seconds',
            'outlier_detection_max_ejection_percent',
            'health_checks_enabled',
            'health_check_timeout_seconds',
            'health_check_interval_seconds',
            'health_check_unhealthy_threshold',
            'health_check_healthy_threshold',
            'healthy_panic_threshold',
            'effective_health_check_timeout_seconds',
        ]

    def get_effective_health_check_timeout_seconds(self, obj):
        return obj.get_effective_health_check_timeout_seconds()
