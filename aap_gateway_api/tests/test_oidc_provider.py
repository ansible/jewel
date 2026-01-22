from unittest.mock import patch

import pytest

from aap_gateway_api.oidc_provider import LazyPrivateKey


def test_lazy_private_key_encode():
    mock_key = 'mock_rsa_private_key'

    with patch('aap_gateway_api.utils.jwt_token.get_jwt_rsa_key', return_value=mock_key):
        lazy_key = LazyPrivateKey()
        result = lazy_key.encode('utf-8')
        assert result == mock_key.encode('utf-8')


def test_lazy_private_key_encode_handles_none():
    with patch('aap_gateway_api.utils.jwt_token.get_jwt_rsa_key', return_value=None):
        lazy_key = LazyPrivateKey()
        with pytest.raises(AttributeError):
            lazy_key.encode('utf-8')
