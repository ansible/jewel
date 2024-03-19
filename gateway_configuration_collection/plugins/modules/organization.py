#!/usr/bin/python
# coding: utf-8 -*-
#
# Apache-2.0

from __future__ import absolute_import, division, print_function

__metaclass__ = type


ANSIBLE_METADATA = {
    "metadata_version": "0.0.1",
    "status": ["preview"],
    "supported_by": "community",
}

DOCUMENTATION = """
---
module: organization
author: Red Hat
short_description: Configure a gateway organization.
description:
    - Configure an automation platform gateway organizations.
options:
    name:
      required: true
      type: str
      description: The name of the organization, must be unique
    new_name:
      type: str
      description: Setting this option will change the existing name (looked up via the name field)
    description:
      description: The description of the Organization
      type: str
    users:
      type: list
      description: List of user IDs associated with the organization
    admins:
      type: list
      description: List of user IDs associated with the organization as administrators
extends_documentation_fragment:
- infra.gateway_configuration.state
- infra.gateway_configuration.auth
"""

EXAMPLES = """
- name: Create Organization
  infra.gateway_configuration.organization:
  - name: Ansible Product Development
    description: Organization for ansible developers
    users:
    - 1
    - 2

- name: Update Organization
  infra.gateway_configuration.organization:
  - name: Ansible Product Development
    admins:
    - 5

- name: Delete Organization
  infra.gateway_configuration.organization:
  - name: Ansible Product Development
    state: absent
"""

from ..module_utils.aap_module import AAPModule  # noqa
from ..module_utils.aap_organization import AAPOrganization  # noqa


def main():
    argument_spec = dict(
        name=dict(type="str", required=True),
        new_name=dict(type="str"),
        description=dict(type="str"),
        users=dict(type="list"),
        admins=dict(type="list"),
        state=dict(choices=["present", "absent", "exists", "enforced"], default="present"),
    )

    # Create a module with spec
    module = AAPModule(argument_spec=argument_spec, supports_check_mode=True)

    AAPOrganization(module).manage()


if __name__ == "__main__":
    main()
