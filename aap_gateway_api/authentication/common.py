from aap_gateway_api.models import User


def check_user_attribute_map(user_attr_map: dict, name: str = 'USER_ATTR_MAP') -> dict:
    errors = {}
    if type(user_attr_map) is not dict:
        errors[name] = "Must be dict"
        return errors

    valid_user_attr_fields = set(["email", "username", "first_name", "last_name"])
    given_fields = set(list(user_attr_map.keys()))

    missing_required_fields = set(User.REQUIRED_FIELDS) - given_fields
    for field in missing_required_fields:
        errors[f"{name}.{field}"] = "Must be present"

    invalid_fields = given_fields - valid_user_attr_fields
    for field in invalid_fields:
        errors[f"{name}.{field}"] = "Is not valid"

    valid_fields = given_fields.intersection(valid_user_attr_fields)
    for field in valid_fields:
        if type(user_attr_map[field]) is not str:
            errors[f"{name}.{field}"] = "Must be a string"

    return errors
