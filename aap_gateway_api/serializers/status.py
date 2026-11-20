from ansible_base.lib.constants import STATUS_DEGRADED, STATUS_FAILED, STATUS_GOOD
from ansible_base.lib.utils.views.deprecation import DeprecationSerializerMixin
from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

status_choices = serializers.ChoiceField(required=False, choices=[STATUS_GOOD, STATUS_DEGRADED, STATUS_FAILED])
DEPRECATED_CONNECTIVITY_FIELD_HELP_TEXT = "DEPRECATED: This field is deprecated and will be removed in a future version."


# Serializers for status and ping pages.
class ClusterInfoSerializer(serializers.Serializer):
    cluster_state = serializers.CharField(required=False)
    cluster_slots_assigned = serializers.CharField(required=False)
    cluster_slots_ok = serializers.CharField(required=False)
    cluster_slots_pfail = serializers.CharField(required=False)
    cluster_slots_fail = serializers.CharField(required=False)
    cluster_known_nodes = serializers.CharField(required=False)
    cluster_size = serializers.CharField(required=False)
    cluster_current_epoch = serializers.CharField(required=False)
    cluster_my_epoch = serializers.CharField(required=False)
    cluster_stats_messages_ping_sent = serializers.CharField(required=False)
    cluster_stats_messages_pong_sent = serializers.CharField(required=False)
    cluster_stats_messages_sent = serializers.CharField(required=False)
    cluster_stats_messages_ping_received = serializers.CharField(required=False)
    cluster_stats_messages_pong_received = serializers.CharField(required=False)
    cluster_stats_messages_received = serializers.CharField(required=False)


@extend_schema_serializer(deprecate_fields=["db_connected", "proxy_connected"])
class PingSerializer(DeprecationSerializerMixin, serializers.Serializer):
    version = serializers.CharField(required=False)
    pong = serializers.DateTimeField(required=False)
    status = status_choices
    db_connected = serializers.BooleanField(required=False, help_text=DEPRECATED_CONNECTIVITY_FIELD_HELP_TEXT)
    db_exception = serializers.CharField(required=False)
    proxy_connected = serializers.BooleanField(required=False, help_text=DEPRECATED_CONNECTIVITY_FIELD_HELP_TEXT)
    proxy_status_code = serializers.IntegerField(required=False)
    proxy_exception_type = serializers.CharField(required=False)
    dispatcherd_connected = serializers.BooleanField(required=False)

    deprecated_fields = {
        "db_connected": "The 'db_connected' field is deprecated and will be removed in a future version.",
        "proxy_connected": "The 'proxy_connected' field is deprecated and will be removed in a future version.",
    }


class RedisResponseSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(required=False, choices=["cluster", "standalone", "Unknown"])
    status = status_choices
    ping = serializers.BooleanField(required=False)
    cluster_info = ClusterInfoSerializer(required=False)


class StatusNodeSerializer(serializers.Serializer):
    url = serializers.CharField(required=False)
    status = status_choices
    exception = serializers.CharField(required=False)
    response = PingSerializer(required=False)
    response_code = serializers.IntegerField(required=False)
    node_id = serializers.CharField(required=False)
    hostname = serializers.CharField(required=False)
    flags = serializers.CharField(required=False)
    master_id = serializers.CharField(required=False)
    last_ping_sent = serializers.CharField(required=False)
    last_pong_rcvd = serializers.CharField(required=False)
    epoch = serializers.CharField(required=False)
    slots = serializers.ListField(required=False, child=serializers.ListField(child=serializers.CharField()))
    migrations = serializers.ListField(required=False, child=serializers.CharField())
    connected = serializers.BooleanField(required=False)
    body = serializers.CharField(required=False)


class StatusServiceSerializer(serializers.Serializer):
    service_name = serializers.CharField(required=False)
    status = status_choices
    nodes = serializers.DictField(child=StatusNodeSerializer())
    response = RedisResponseSerializer(required=False)


class StatusSerializer(serializers.Serializer):
    time = serializers.DateTimeField()
    status = status_choices
    services = serializers.ListField(child=StatusServiceSerializer())


class ServiceKeysStatusSerializer(serializers.Serializer):
    time = serializers.DateTimeField()
    status = status_choices
    services = serializers.DictField(child=StatusServiceSerializer())
