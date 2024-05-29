from django.core.cache import cache

JWT_SESSION_PREFIX = "jwt-session-"


class JWTSessionCache:
    @staticmethod
    def set(user_pk, jwt):
        from aap_gateway_api.utils import get_preference_value

        # try to invalidate the cache -before- the token expires so that
        # there isn't a window of time where the cache serves out an expired
        # token and causes 401s for the client.
        delta = get_preference_value("proxy", "jwt_expiration_buffer_in_seconds")
        timeout = get_preference_value("proxy", "gateway_access_token_expiration") - delta

        return cache.set(JWT_SESSION_PREFIX + str(user_pk), jwt, timeout=timeout)

    @staticmethod
    def get(user_pk):
        return cache.get(JWT_SESSION_PREFIX + str(user_pk))

    @staticmethod
    def remove(user_pk):
        return cache.delete(JWT_SESSION_PREFIX + str(user_pk))
