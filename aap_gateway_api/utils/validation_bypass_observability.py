"""Register django-ansible-base ORM bypass caller attribution for Gateway."""

from ansible_base.lib.utils.validation_signals import (
    extend_caller_allowlist_prefixes,
    extend_internal_caller_prefixes,
    register_validation_signals,
)


def configure_validation_bypass_observability() -> None:
    register_validation_signals()
    extend_caller_allowlist_prefixes(
        [
            "aap_gateway_api.views",
            "aap_gateway_api.serializers",
            "aap_gateway_api.tasks",
            "aap_gateway_api.management",
        ]
    )
    extend_internal_caller_prefixes(
        [
            "aap_gateway_api.models",
            "aap_gateway_api.signals",
        ]
    )
