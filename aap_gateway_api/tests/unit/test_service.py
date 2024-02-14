import pytest
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError


@pytest.mark.django_db(transaction=True)
def test_httpport_api_port_unique(http_api_port_factory):
    from aap_gateway_api.models import HTTPPort

    http_api_port_factory()
    with pytest.raises(IntegrityError):
        port = HTTPPort()
        port.name = "port-1337"
        port.number = 1337
        port.is_api_port = True
        port.save(non_existent_user_fatal=False)


@pytest.mark.django_db
def test_additional_route_model_clean(http_api_port_factory, service_cluster_eda):
    from aap_gateway_api.models import AdditionalRoute

    http_api_port = http_api_port_factory()
    with pytest.raises(ValidationError) as e:
        AdditionalRoute.objects.create(
            name="foo",
            is_service_https=False,
            port=http_api_port,
            service_path="/test",
            service_cluster=service_cluster_eda,
            service_port=6667,
            gateway_path="/api/test",
        )

    assert "Custom routes on the API port cannot start with '/api/'" in str(e.value)
