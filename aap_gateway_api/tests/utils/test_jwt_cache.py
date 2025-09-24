from unittest import mock

from aap_gateway_api.utils.jwt_cache import JWTSessionCache


def test_jwt_token_cache_expiration_delta(preference_manager):
    """
    Make sure the cache timeout is computed properly from preferences.
    """
    with preference_manager.set_multiple(
        {
            ("proxy", "jwt_expiration_buffer_in_seconds"): 5,
            ("proxy", "gateway_access_token_expiration"): 15,
        }
    ):
        with mock.patch('aap_gateway_api.utils.jwt_cache.cache') as mocked_cache:
            JWTSessionCache.set("abcd", "supersecretkey")

        mocked_call = mocked_cache.mock_calls[0]
        assert mocked_call.args == ("jwt-session-abcd", "supersecretkey")
        assert mocked_call.kwargs["timeout"] == 10
