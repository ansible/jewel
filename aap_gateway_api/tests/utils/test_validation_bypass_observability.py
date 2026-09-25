import pytest

from aap_gateway_api.utils.validation_bypass_observability import (
    configure_validation_bypass_observability,
)


@pytest.mark.django_db
def test_configure_validation_bypass_observability_wires_dab(mocker):
    mocker.patch(
        "aap_gateway_api.utils.validation_bypass_observability.register_validation_signals"
    )
    allow = mocker.patch(
        "aap_gateway_api.utils.validation_bypass_observability.extend_caller_allowlist_prefixes"
    )
    deny = mocker.patch(
        "aap_gateway_api.utils.validation_bypass_observability.extend_internal_caller_prefixes"
    )
    import_serializers = mocker.patch(
        "aap_gateway_api.utils.validation_bypass_observability._import_registry_serializers"
    )

    configure_validation_bypass_observability()

    allow.assert_called_once()
    prefixes = allow.call_args[0][0]
    assert "aap_gateway_api.serializers" in prefixes
    deny.assert_called_once()
    internal = deny.call_args[0][0]
    assert "aap_gateway_api.utils.validation_bypass_observability" in internal
    assert "aap_gateway_api.utils.service_id_sync" in internal
    import_serializers.assert_called_once()
