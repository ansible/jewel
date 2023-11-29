import logging

from cryptography.hazmat.primitives import serialization
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from dynamic_preferences import types

logger = logging.getLogger("aap.gateway.preference_types")


class URLPreference(types.StringPreference):
    def validate(self, value):
        if not self.required and not value:
            # If this preference is not required and we didn't get a value we can just return
            #  because '' or None is not a valid URL and will trip up the URLValidator
            return value

        try:
            validator = URLValidator(schemes=["https"])
            validator(value)
        except ValidationError:
            raise ValidationError(f"{value} is not a valid URL")

        return value


class PEMPrivateKeyPreference(types.LongStringPreference):
    def validate(self, value):
        logger.debug("Validating PEM private key")
        try:
            serialization.load_pem_private_key(bytes(value, "UTF-8"), password=None)
        except Exception:
            logger.exception("Unable to load private key from PEM key")
            raise ValidationError("Unable to load private key from PEM key")

        return value
