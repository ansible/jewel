from django.core.cache import cache

JWT_SESSION_PREFIX = "jwt-session-"


class JWTSessionCache:
    @staticmethod
    def set(session, jwt):
        from aap_gateway_api.utils import get_preference_value

        return cache.set(JWT_SESSION_PREFIX + session, jwt, timeout=get_preference_value("proxy", "gateway_access_token_expiration"))

    @staticmethod
    def get(session):
        return cache.get(JWT_SESSION_PREFIX + session)

    @staticmethod
    def remove(session):
        return cache.delete(JWT_SESSION_PREFIX + session)
