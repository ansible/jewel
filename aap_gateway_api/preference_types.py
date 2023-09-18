from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from dynamic_preferences import types


class URLPreference(types.StringPreference):
    def validate(self, value):
        try:
            validator = URLValidator(schemes=["https"])
            validator(value)
        except ValidationError:
            raise ValidationError(f"{value} is not a valid URL")

        return value


