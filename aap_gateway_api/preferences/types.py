import logging

from ansible_base.lib.utils.validation import validate_image_data
from cryptography.hazmat.primitives import serialization
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils.translation import gettext as _
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
            raise ValidationError(_("%(value)s is not a valid URL") % {"value": value})

        return value


class PEMPrivateKeyPreference(types.LongStringPreference):
    def validate(self, value):
        logger.debug("Validating PEM private key")
        try:
            serialization.load_pem_private_key(bytes(value, "UTF-8"), password=None)
        except Exception:
            logger.exception("Unable to load private key from PEM key")
            raise ValidationError(_("Unable to load private key from PEM key"))

        return value


class MimeTypedImagePreference(types.LongStringPreference):
    def validate(self, value):
        """Check that an uploaded image file is valid data and in valid format"""
        validate_image_data(value)
        return value
