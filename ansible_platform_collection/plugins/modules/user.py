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
    is_platform_auditor:
      description:
        - Designates that this user is a platform auditor.
      type: bool
      aliases: ['auditor']
    password:
      description:
        - Write-only field used to change the password.
      type: str
    organizations:
      description:
        - List of organizations IDs to associate with the user
      type: list
      elements: str
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
    if module.params["is_platform_auditor"]:
        module.deprecate(
            msg="Configuring auditor via `ansible.platform.user` is not the recommended approach. "
            "The preferred method going forward is to use the `role_user_assignment` module.",
            date="2026-12-01",
            collection_name="ansible.platform",
        )

    # Process the user first
    AAPUser(module).manage(auto_exit=False)

    # Only process organizations if the state is present or enforced
    if module.params.get('state') in ['present', 'enforced']:
        audit_user(module)

    # Exit with the final status
    module.exit_json(**module.json_output)


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
