from unittest.mock import patch

import pytest


@pytest.fixture
def cache_backend(settings):
    settings.CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'test-gateway-cache',
        }
    }
    from django.core.cache import cache

    cache.clear()
    cache.set('gw_key_a', 'val_a')
    cache.set('gw_key_b', 'val_b')
    yield cache
    cache.clear()


def test_clear_gateway_cache_deletes_keys(cache_backend):
    from aap_gateway_api.tasks.cache import clear_gateway_cache

    clear_gateway_cache(['gw_key_a'])

    assert cache_backend.get('gw_key_a') is None
    assert cache_backend.get('gw_key_b') == 'val_b'


def test_clear_gateway_cache_delegates_to_dab(cache_backend):
    with patch('aap_gateway_api.tasks.cache.clear_cache') as mock_clear:
        from aap_gateway_api.tasks.cache import clear_gateway_cache

        clear_gateway_cache(['key_x', 'key_y'])

        mock_clear.assert_called_once_with(['key_x', 'key_y'])


def test_clear_gateway_cache_empty_list(cache_backend):
    from aap_gateway_api.tasks.cache import clear_gateway_cache

    clear_gateway_cache([])

    assert cache_backend.get('gw_key_a') == 'val_a'
    assert cache_backend.get('gw_key_b') == 'val_b'


def test_tasks_cache_module_importable():
    import aap_gateway_api.tasks.cache as cache_module

    assert hasattr(cache_module, 'clear_gateway_cache')
