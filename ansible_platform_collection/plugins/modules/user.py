#!/usr/bin/python
# coding: utf-8 -*-

# (c) 2020, John Westcott IV <john.westcott.iv@redhat.com>
# (c) 2023, Sean Sullivan <@sean-m-sullivan>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type


DOCUMENTATION = """
---
module: user
author: Sean Sullivan (@sean-m-sullivan)
short_description: Configure a gateway user.
description:
    - Configure an automation platform gateway user.
options:
    organizations:
      description:
        - B(Deprecated)
        - This option is deprecated and will be removed in a release after 2026-01-31.
        - For associating a user to an organization, please use the ansible.platform.role_user_assignment module.
        - HORIZONTALLINE
        - List of organization names or IDs to associate with the user.
        - Organizations must already exist - the module will not create missing organizations.
        - If any specified organization doesn't exist, the operation will fail.
        - If a user was created as part of this operation and an organization association fails, the newly created user will be removed.
      type: list
      elements: str
    is_platform_auditor:
      description:
        - B(Deprecated)
        - This option is deprecated and will be removed in a release after 2026-01-31.
        - For designating a user as an auditor, please use the ansible.platform.role_user_assignment module.
        - HORIZONTALLINE
        - Designates that this user is a platform auditor.
      type: bool
      aliases: ['auditor']
    username:
      description:
        - Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
      required: True
      type: str
    first_name:
      description:
        - First name of the user.
      type: str
    last_name:
      description:
        - Last name of the user.
      type: str
    email:
      description:
        - Email address of the user.
      type: str
    is_superuser:
      description:
        - Designates that this user has all permissions without explicitly assigning them.
      type: bool
      aliases: ['superuser']
    password:
      description:
        - Write-only field used to change the password.
      type: str
    update_secrets:
      description:
        - C(true) will always change password if user specifies password, even if API gives $encrypted$ for password.
        - C(false) will only set the password if other values change too.
      type: bool
      default: true
    authenticators:
      description:
        - A list of authenticators to associate the user with
      type: list
      elements: str
    authenticator_uid:
      description:
        - The UID to associate with this users authenticators
      type: str

extends_documentation_fragment:
- ansible.platform.state
- ansible.platform.auth
"""


EXAMPLES = """
- name: Add user
  ansible.platform.user:
    username: jdoe
    password: foobarbaz
    email: jdoe@example.org
    first_name: John
    last_name: Doe
    state: present

- name: Add user as a system administrator
  ansible.platform.user:
    username: jdoe
    password: foobarbaz
    email: jdoe@example.org
    superuser: true
    state: present

- name: Add user as a system auditor
  ansible.platform.user:
    username: jdoe
    password: foobarbaz
    email: jdoe@example.org
    auditor: true
    state: present

- name: Delete user
  ansible.platform.user:
    username: jdoe
    email: jdoe@example.org
    state: absent
...
"""

from ..module_utils.aap_module import AAPModule  # noqa
from ..module_utils.aap_user import AAPUser  # noqa


def main():
    # Any additional arguments that are not fields of the item can be added here
    argument_spec = dict(
        username=dict(required=True),
        first_name=dict(),
        last_name=dict(),
        email=dict(),
        is_superuser=dict(type="bool", aliases=["superuser"]),
        is_platform_auditor=dict(type="bool", aliases=["auditor"]),
        password=dict(no_log=True),
        organizations=dict(type="list", elements='str'),
        update_secrets=dict(type="bool", default=True, no_log=False),
        authenticators=dict(type="list", elements='str'),
        authenticator_uid=dict(),
        state=dict(choices=["present", "absent", "exists", "enforced"], default="present"),
    )

    # Create a module for ourselves
    module = AAPModule(argument_spec=argument_spec, supports_check_mode=True)

    if module.params["organizations"]:
        module.deprecate(
            msg="Configuring organizations via `ansible.platform.user` is not the recommended approach. "
            "The preferred method going forward is to use the `ansible.platform.role_user_assignment` module.",
            date="2026-01-31",
            collection_name="ansible.platform",
        )

    if module.params["is_platform_auditor"]:
        module.deprecate(
            msg="Configuring auditor via `ansible.platform.user` is not the recommended approach. "
            "The preferred method going forward is to use the `ansible.platform.role_user_assignment` module.",
            date="2026-01-31",
            collection_name="ansible.platform",
        )

    user_existed_before = True
    try:
        existing_user = module.get_one('users', module.params.get('username'), allow_none=True)
        user_existed_before = existing_user is not None
    except (ConnectionError, TimeoutError) as e:
        module.fail_json(msg=f"Connection error while checking if user exists: {str(e)}")

    AAPUser(module).manage(auto_exit=False)

    if module.params.get('state') in ['present', 'enforced']:
        process_organizations(module, user_existed_before)
        audit_user(module)

    module.exit_json(**module.json_output)


def process_organizations(module, user_existed_before):
    changed = module.json_output.get('changed', False)
    organizations = module.params.get('organizations')
    error_msg = []
    user_id = None

    if not organizations:
        return

    try:
        if not module.json_output.get('id'):
            user_data = module.get_one('users', module.params.get('username'), allow_none=False)
            user_id = user_data['id']
            module.json_output['id'] = user_id
        else:
            user_id = module.json_output['id']
    except (ConnectionError, TimeoutError) as e:
        error_msg.append(f"Connection error while retrieving user information: {str(e)}")
    except ValueError as e:
        error_msg.append(f"Invalid value or parameter: {str(e)}")

    try:
        role_definition = module.get_one('role_definitions', "Organization Member", allow_none=False)
        role_definition_id = role_definition['id']
    except ConnectionError as e:
        error_msg.append(f"Failed to fetch role definition: {str(e)}")

    for organization in organizations:
        try:
            org = module.get_one('organizations', organization, allow_none=True)
            if not org:
                error_msg.append(f"Organization '{organization}' not found. Please ensure it exists and is accessible.")
                continue

            org_id = org['id']
            url = module.build_url("role_user_assignments")
            payload = {"object_id": org_id, "user": user_id, "role_definition": role_definition_id}
            associate_result = module.make_request("POST", url, data=payload)
            if associate_result.get('status_code') not in [200, 201]:
                error_msg.append(f"Failed to associate user with organization {organization}. API response: {associate_result}")
                continue
            changed = True
        except (ConnectionError, TimeoutError) as e:
            error_msg.append(f"Connection error while processing organization '{organization}': {str(e)}")
            continue

        module.json_output['changed'] = changed

    if error_msg and not user_existed_before and user_id:
        if cleanup_user(module, user_id):
            error_msg.append(f"\nNewly created user '{module.params.get('username')}' was removed.")
        else:
            error_msg.append("\nFailed to clean up newly created user. Manual cleanup may be required.")

    if error_msg:
        module.fail_json(msg=error_msg)


def cleanup_user(module, user_id):

    try:
        delete_url = module.build_url(f'users/{user_id}/')
        delete_result = module.make_request('DELETE', delete_url)
        return delete_result.get('status_code') == 204
    except (ConnectionError, TimeoutError):
        return False


def audit_user(module):
    try:
        user_data = module.get_one('users', module.params.get('username'), allow_none=False)
        user_id = user_data['id']
    except Exception as e:
        module.fail_json(msg=f"Failed to fetch user data: {str(e)}")
    try:
        role_definition = module.get_one('role_definitions', "Platform Auditor", allow_none=False)
        role_definition_id = role_definition['id']
    except Exception as e:
        module.fail_json(msg=f"Failed to fetch role definition: {str(e)}")
    if module.params.get('is_platform_auditor') and not user_data['is_platform_auditor']:
        payload = {
            "role_definition": role_definition_id,
            "user": user_id,
        }
        url = module.build_url("role_user_assignments/")
        try:
            module.make_request("POST", url, data=payload)
            module.json_output["changed"] = True
        except Exception as e:
            module.fail_json(msg=f"Failed to assign platform auditor role: {str(e)}")

    if module.params.get('is_platform_auditor') is False and user_data['is_platform_auditor']:
        kwargs = {'role_definition': role_definition_id, 'user': user_id}
        try:
            role_user_assignment = module.get_one('role_user_assignments', **{'data': kwargs})['id']
        except Exception as e:
            module.fail_json(msg=f"Failed to fetch role user assignment: {str(e)}")
        user_data['is_platform_auditor'] = False
        url = module.build_url(f"role_user_assignments/{role_user_assignment}")
        try:
            module.make_request("DELETE", url)
            module.json_output["changed"] = True
        except Exception as e:
            module.fail_json(msg=f"Failed to remove platform auditor role: {str(e)}")


if __name__ == "__main__":
    main()
