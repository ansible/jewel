import logging

from cryptography.hazmat.primitives import serialization
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from dynamic_preferences import types

logger = logging.getLogger("aap_gateway_api.preference_types")


class URLPreference(types.StringPreference):
    def validate(self, value):
        try:
            validator = URLValidator(schemes=["https"])
            validator(value)
        except ValidationError:
            raise ValidationError(f"{value} is not a valid URL")

        return value


class PEMPrivateKeyPreference(types.LongStringPreference):
    def validate(self, value):
        logger.debug("Validating PEM private key")
        if value == "":
            # TODO: Do we want to allow this case?
            logger.debug("PEM private key is empty")
            return value
        try:
            serialization.load_pem_private_key(bytes(value, "UTF-8"), password=None)
        except Exception:
            logger.exception("Unable to load private key from PEM key")
            raise ValidationError("Unable to load private key from PEM key")

        return value
