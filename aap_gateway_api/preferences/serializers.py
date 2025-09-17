import json
import logging

from django.conf import settings
from dynamic_preferences.serializers import BaseSerializer

from aap_gateway_api.utils.requests import check_csrf_origin

logger = logging.getLogger("aap.gateway.preferences.serializers")


class JSONString(str):
    def __new__(cls, value):
        ret = str.__new__(cls, value)
        ret.is_json_string = True
        return ret


class JSONSerializer(BaseSerializer):
    @classmethod
    def to_python(cls, value, **kwargs):
        if value is None:
            return json.loads('null')
        try:
            ret = json.loads(value)
        except Exception:
            try:
                ret = json.loads(f'"{value}"')
            except Exception as e:
                raise cls.exception(f"Unable to convert value {value} from JSON: {e}")

        if type(ret) is str:
            ret = JSONString(ret)
            return ret
        return ret

    @classmethod
    def to_db(cls, value, **kwargs):
        try:
            return super().to_db(json.dumps(value), **kwargs)
        except Exception as e:
            raise cls.exception(f"Unable to convert value {value} into JSON: {e}")


class CSRFSerializer(JSONSerializer):
    @classmethod
    def to_python(cls, value, **kwargs):
        ret = super().to_python(value, **kwargs)
        if type(ret) is not list:
            logger.error(f"Got a non-list value type {type(ret)} from {ret}, defaulting to []")
            ret = []

        valid_values = []
        for url in getattr(settings, 'CSRF_TRUSTED_ORIGINS', []):
            invalid_reason = check_csrf_origin(url)
            if invalid_reason is None:
                valid_values.append(url)
            else:
                logger.error(f"CSRF_TRUSTED_ORIGINS has an invalid value: {invalid_reason}")

        return valid_values + ret

    @classmethod
    def to_db(cls, value, **kwargs):
        csrf_settings = set(getattr(settings, "CSRF_TRUSTED_ORIGINS", []))
        save_values = list(set(value).difference(csrf_settings))
        return super().to_db(save_values, **kwargs)
