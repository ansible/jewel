import json

from dynamic_preferences.serializers import BaseSerializer


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
