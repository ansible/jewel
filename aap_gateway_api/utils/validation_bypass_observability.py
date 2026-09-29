"""Register django-ansible-base ORM bypass observability for Gateway.

Gateway has few bulk import paths; focus on caller registration and loading
serializers so ``_protected_models`` is populated. See DAB
``docs/lib/validation_bypass_observability.md``.
"""

from ansible_base.lib.utils.validation_signals import extend_caller_allowlist_prefixes, extend_internal_caller_prefixes, register_validation_signals


def _import_registry_serializers() -> None:
    """Load CleanTextMixin serializers (Gateway + shared DAB API models)."""
    import ansible_base.authentication.serializers  # noqa: F401
    import ansible_base.rbac.api.serializers  # noqa: F401

    import aap_gateway_api.serializers  # noqa: F401


def configure_validation_bypass_observability() -> None:
    """Call from ``MyAppConfig.ready()``."""
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
            "aap_gateway_api.utils.validation_bypass_observability",
            "aap_gateway_api.utils.service_id_sync",
        ]
    )
    _import_registry_serializers()
