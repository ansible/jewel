from django.conf import settings
from django.core.cache import cache

JWT_SESSION_PREFIX = "jwt-session-"


class JWTSessionCache:
    @staticmethod
    def set(session, jwt):
        return cache.set(JWT_SESSION_PREFIX + session, jwt, timeout=settings.GATEWAY_ACCESS_TOKEN_EXIPIRATION)

    @staticmethod
    def get(session):
        return cache.get(JWT_SESSION_PREFIX + session)

    @staticmethod
    def remove(session):
        return cache.delete(JWT_SESSION_PREFIX + session)
