from io import StringIO

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_list_services_with_objects(service_cluster_hub, service_node_hub, additional_route_hub):
    """Validate the list_services command emits some key phrases."""

    # call the list ...
    out = StringIO()
    call_command('list_services', stdout=out)
    stdout = out.getvalue()

    assert 'cluster: hub' in stdout
    assert 'node: Service Node' in stdout
    assert 'AdditionalRoute: Test route' in stdout
    assert 'port: ' in stdout
    assert 'gateway_path: ' in stdout
    assert 'enable_gateway_auth: ' in stdout
    assert 'is_service_https: ' in stdout
    assert 'service_port: ' in stdout
    assert 'service_path: ' in stdout
