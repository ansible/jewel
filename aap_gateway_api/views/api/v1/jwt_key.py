import logging

from cryptography.hazmat.primitives import serialization
from django.http import HttpResponse
from django.views import View

from aap_gateway_api.utils import get_jwt_rsa_key

logger = logging.getLogger('jwt_key')


class JWTKeyView(View):
    def get(self, request, *args, **kwargs):
        jwt_key = get_jwt_rsa_key()

        private_key = None
        try:
            private_key = serialization.load_pem_private_key(bytes(jwt_key, "UTF-8"), password=None)
        except Exception as e:
            logger.exception("Unable to load private key from JWT key")
            raise e

        try:
            public_key = (
                private_key.public_key()
                .public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                )
                .decode()
            )
            return HttpResponse(public_key)
        except Exception as e:
            logger.exception("Unable to export public key from JWT key")
            raise e
