import logging
from datetime import datetime, timedelta

import jwt
from django.conf import settings

logger = logging.getLogger('aap.gateway.utils.jwt_token')


def create_signed_jwt(user):
    due_date = datetime.now() + timedelta(seconds=settings.GATEWAY_ACCESS_TOKEN_EXIPIRATION)
    payload = {
        "iss": "aap-gateway",
        "exp": int(due_date.timestamp()),
        "aud": "aap-services",
        "sub": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "is_superuser": user.is_superuser,
        # FIXME: what's the flag for system auditor?
        "is_system_auditor": user.is_superuser,
        "claims": {"organizations": {}, "teams": {}},
    }
    if hasattr(user, 'claim'):
        payload["claims"] = user.claim.data
    token = jwt.encode(payload, get_jwt_rsa_key(), algorithm='RS256')
    return token


def get_jwt_rsa_key():
    jwt_key_setting_name = 'JWT_KEY'
    jwt_key = getattr(settings, jwt_key_setting_name, None).strip()

    if not jwt_key:
        logger.error(f'{jwt_key_setting_name} setting is not defined')
        raise RuntimeError(f'{jwt_key_setting_name} is not set')

    return jwt_key
