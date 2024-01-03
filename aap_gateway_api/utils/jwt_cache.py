from django.core.cache import cache

JWT_SESSION_PREFIX = "jwt-session-"


class JWTSessionCache:
    @staticmethod
    def set(user_pk, jwt):
        from aap_gateway_api.utils import get_preference_value

        return cache.set(JWT_SESSION_PREFIX + str(user_pk), jwt, timeout=get_preference_value("proxy", "gateway_access_token_expiration"))

    @staticmethod
    def get(user_pk):
        return cache.get(JWT_SESSION_PREFIX + str(user_pk))

    @staticmethod
    def remove(user_pk):
        return cache.delete(JWT_SESSION_PREFIX + str(user_pk))
