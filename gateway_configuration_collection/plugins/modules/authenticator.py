#!/usr/bin/python
# coding: utf-8 -*-

# Copyright: (c) 2024, Martin Slemr <@slemrmartin>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type


DOCUMENTATION = """
---
module: authenticator
author: Red Hat (@RedHatOfficial)
short_description: Configure a gateway authenticator.
description:
    - Configure an automation platform gateway authenticators.
options:
    name:
      required: true
      type: str
      description: The name of the authenticator, must be unique
    new_name:
      type: str
      description: Setting this option will change the existing name (looked up via the name field)
    slug:
      type: str
      description:
      - An immutable identifier for the authenticator
      - Must be unique
      - If not provided, it's auto-generated
    enabled:
      type: bool
      description:
      - Enable/Disable the authenticator
      - Defaults to false (by API)
    create_objects:
      type: bool
      description:
      - Allow authenticator to create objects (users, teams, organizations)
      - Defaults to true (by API)
    remove_users:
      type: bool
      default: true
      description: When a user authenticates from this source should they be removed from any other groups they were previously added to
    type:
      type: str
      description:
      - The type of authentication service this is
      - Can be one of the modules: 'ansible_base.authentication.authenticator_plugins.*'
      - https://github.com/ansible/django-ansible-base/tree/devel/ansible_base/authentication/authenticator_plugins
    configuration:
      type: dict
      default: {}
      description:
      - The required configuration for this source
      - dict keys specified by the module in option 'type'
    order:
      type: int
      description:
      - The order in which an authenticator will be tried. This only pertains to username/password authenticators
      - defaults to 1 (by API)
extends_documentation_fragment:
- ansible.gateway_configuration.state
- ansible.gateway_configuration.auth
"""

EXAMPLES = """
"""


from ..module_utils.aap_authenticator import AAPAuthenticator  # noqa
from ..module_utils.aap_module import AAPModule  # noqa


def main():
    argument_spec = dict(
        name=dict(type="str", required=True),
        new_name=dict(type="str"),
        slug=dict(type="str"),
        enabled=dict(type="bool"),
        create_objects=dict(type="bool"),
        remove_users=dict(type="bool"),
        type=dict(type="str"),
        configuration=dict(type="dict", no_log=True),  # can contain secrets
        order=dict(type="int"),
        state=dict(choices=["present", "absent", "exists", "enforced"], default="present"),
    )

    # Create a module with spec
    module = AAPModule(argument_spec=argument_spec, supports_check_mode=True)

    AAPAuthenticator(module).manage()


if __name__ == "__main__":
    main()
