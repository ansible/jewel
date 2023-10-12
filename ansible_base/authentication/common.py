import logging
import re

from django.contrib.auth import get_user_model

from ansible_base.models import Authenticator, AuthenticatorMap

from .trigger_definition import TRIGGER_DEFINITION

User = get_user_model()

logger = logging.getLogger('ansible_base.authentication.common')


def check_user_attribute_map(user_attr_map: dict, name: str = 'USER_ATTR_MAP') -> dict:
    # Validates an attribute map to user map.
    # i.e. does the authenticator know how to extract email, username, first_name, last_name, etc
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


def create_claims(authenticator: Authenticator, username: str, attrs: dict, groups: list) -> (bool, bool, dict, list):
    # Assume we are not going to change our flags
    is_superuser = None
    is_system_auditor = None
    # Assume we start with no mappings
    org_team_mapping = {}
    # Start with an empty rule responses
    rule_responses = []
    # Assume we will have access
    access_allowed = True
    logger.info(f"Creating mapping for user {username} through authenticator {authenticator.name}")
    logger.debug(f"{username}'s groups: {groups}")
    logger.debug(f"{username}'s attrs: {attrs}")

    # load the maps
    maps = AuthenticatorMap.objects.filter(authenticator=authenticator.id).order_by("order")
    for auth_map in maps:
        has_permission = None
        allowed_keys = TRIGGER_DEFINITION.keys()
        invalid_keys = set(auth_map.triggers.keys()) - set(allowed_keys)
        if invalid_keys:
            logger.warning(f"In AuthenticatorMap {auth_map.id} the following trigger keys are invalid: {', '.join(invalid_keys)}, rule will be ignored")
            rule_responses.append({auth_map.id: 'invalid'})
            continue

        for trigger_type in auth_map.triggers.keys():
            trigger = auth_map.triggers[trigger_type]

            if trigger_type == 'groups':
                has_permission = process_groups(trigger, groups, authenticator.name)
            if trigger_type == 'attributes':
                has_permission = process_user_attributes(trigger, attrs, authenticator.name)
            if trigger_type == 'always':
                has_permission = True
            if trigger_type == 'never':
                has_permission = False

        # If we didn't get permission and we are set to revoke permission we can set has_permission to False
        if auth_map.revoke and not has_permission:
            has_permission = False

        if has_permission is None:
            rule_responses.append({auth_map.id: 'skipped'})
            continue

        rule_responses.append({auth_map.id: has_permission})

        if auth_map.map_type == 'allow' and not has_permission:
            # If any rule does not allow we don't want to return this to true
            access_allowed = False
        elif auth_map.map_type == 'is_superuser':
            is_superuser = has_permission
        elif auth_map.map_type == 'is_system_auditor':
            is_system_auditor = has_permission
        else:
            if auth_map.organization not in org_team_mapping:
                org_team_mapping[auth_map.organization] = {}
            org_team_mapping[auth_map.organization][auth_map.team] = has_permission

    return {
        "access_allowed": access_allowed,
        "is_superuser": is_superuser,
        "is_system_auditor": is_system_auditor,
        "claims": org_team_mapping,
        "last_login_map_results": rule_responses,
    }


def process_groups(trigger_condition: dict, groups: list, authenticator_id: int) -> bool:
    # Looks at a maps trigger for a group and users groups and determines if the trigger True or False

    invalid_conditions = set(trigger_condition.keys()) - set(TRIGGER_DEFINITION['groups']['keys'].keys())
    if invalid_conditions:
        logger.warning(f"The conditions {', '.join(invalid_conditions)} for groups in mapping {authenticator_id} are invalid and won't be processed")

    has_access = None
    set_of_user_groups = set(groups)

    if "has_or" in trigger_condition:
        if set_of_user_groups.intersection(set(trigger_condition["has_or"])):
            has_access = True
        else:
            has_access = False

    elif "has_and" in trigger_condition:
        if set(trigger_condition["has_and"]).issubset(set_of_user_groups):
            has_access = True
        else:
            has_access = False

    elif "has_not" in trigger_condition:
        if set(trigger_condition["has_not"]).intersection(set_of_user_groups):
            has_access = False
        else:
            has_access = True

    return has_access


def has_access_with_join(current_access: bool, new_access: bool, condition: str = 'or') -> bool:
    if current_access is None:
        return new_access

    if condition == 'or':
        return current_access or new_access

    if condition == 'and':
        return current_access and new_access


def process_user_attributes(trigger_condition: dict, attributes: dict, authenticator_id: int) -> bool:
    # Looks at a maps trigger for an attribute and the users attributes and determines if the trigger is True, False or None

    has_access = None
    join_condition = trigger_condition.get('join_condition', 'or')
    if join_condition not in TRIGGER_DEFINITION['attributes']['keys']['join_condition']['choices']:
        logger.warning("Trigger join_condition {join_condition} on authenticator map {authenticator_id} is invalid and will assumed to be 'or'")
        join_condition = 'or'

    for attribute in trigger_condition.keys():
        if has_access and join_condition == 'or':
            # If we are an or condition and we already have a positive we can break out and return
            break
        elif has_access is False and join_condition == 'and':
            # If we are an and and already have a False we can give up
            break

        # We can skip the join_condition since we already processed that.
        if attribute == 'join_condition':
            continue

        # Warn if there are any invalid conditions, we are just going to ignore them
        invalid_conditions = set(trigger_condition[attribute].keys()) - set(TRIGGER_DEFINITION['attributes']['keys']['*']['keys'].keys())
        if invalid_conditions:
            logger.warning(
                f"The conditions {', '.join(invalid_conditions)} for attribute {attribute} "
                "in authenticator map {authenticator_id} are invalid and won't be processed"
            )

        # The attribute is an empty dict we just need to see if the user has the attribute or not
        if trigger_condition[attribute] == {}:
            has_access = has_access_with_join(has_access, attribute in attributes, join_condition)
            continue

        user_value = attributes.get(attribute, None)
        # If the user does not contain the attribute than we can't check any further, don't set has_access and just continue
        if user_value is None:
            continue

        if type(user_value) is not list:
            # If the value is a string than convert it to a list
            user_value = [user_value]

        for a_user_value in user_value:
            # We are going to do mostly string comparisons, so convert the attribute to a
            #  string just in case it came back as an int or something funky
            a_user_value = f"{a_user_value}"

            # Check for any of the valid conditions
            if "equals" in trigger_condition[attribute]:
                has_access = has_access_with_join(has_access, a_user_value == trigger_condition[attribute]["equals"], join_condition)

            elif "matches" in trigger_condition[attribute]:
                has_access = has_access_with_join(has_access, re.match(trigger_condition[attribute]["matches"], a_user_value, re.IGNORECASE), trigger_condition)

            elif "contains" in trigger_condition[attribute]:
                has_access = has_access_with_join(has_access, {trigger_condition[attribute]['contains']} in a_user_value, join_condition)

            elif "ends_with" in trigger_condition[attribute]:
                has_access = has_access_with_join(has_access, a_user_value.ends_with(trigger_condition[attribute]['ends_with']), join_condition)

            elif "in" in trigger_condition[attribute]:
                has_access = has_access_with_join(has_access, a_user_value in trigger_condition[attribute]['in'], join_condition)

    return has_access
