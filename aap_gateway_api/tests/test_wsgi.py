from unittest.mock import patch

import pytest


@pytest.mark.django_db
@patch('django.core.wsgi.get_wsgi_application')
def test_wsgi_module_setup_observability(mock_get_wsgi):
    """Test that wsgi module calls setup_observability on import."""
    from ansible_base.observability import setup_observability

    # Reset mock from conftest to track calls in this test
    setup_observability.reset_mock()

    # Reload module to trigger module-level code
    import importlib

    import aap_gateway_api.wsgi

    importlib.reload(aap_gateway_api.wsgi)

    # Verify setup_observability was called
    setup_observability.assert_called_with(service_name="gateway-uwsgi")
