from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from dynamic_preferences import types


class URLSerializer(types.StringSerializer):
    @classmethod
    def to_db(cls, value, **kwargs):
        try:
            validator = URLValidator(schemes=['https'])
            validator(value)
        except ValidationError:
            raise cls.exception(f"{value} is not a valid url")

        value = super().to_db(value, **kwargs)

        return value


class URLPreference(types.StringPreference):
    serializer = URLSerializer
