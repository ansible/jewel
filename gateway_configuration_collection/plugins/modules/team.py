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
short_description: Configure a gateway team.
description:
    - Configure an automation platform gateway team.
options:
    name:
      required: true
      type: str
      description: The name of the team, must be unique
    new_name:
      type: str
      description: Setting this option will change the existing name (looked up via the name field)
    description:
      description: The description of the Team
      type: str
    organization:
      type: str
      required: true
      description: The name or ID referencing the Organization
    new_organization:
      type: str
      description: Setting this option will change the existing organization (looked up via the organization field)
    users:
      type: list
      description: List of user IDs associated with the team
    admins:
      type: list
      description: List of user IDs associated with the team as administrators
    parents:
      type: list
      description: List of team IDs that are parents of this team

extends_documentation_fragment:
- infra.gateway_configuration.state
- infra.gateway_configuration.auth
"""

EXAMPLES = """
- name: Create Team
  infra.gateway_configuration.team:
  - name: Gateway Developers
    description: AAP Gateway Developers Team
    organization: Ansible Product Development

- name: Update Team
  infra.gateway_configuration.team:
  - name: Gateway Developers
    organization: "1"
    new_organization: "Red Hat Ansible"
    admins:
    - "5"
    - "7"

- name: Delete Team
  infra.gateway_configuration.team:
  - name: Gateway Developers
    organization: "Red Hat Ansible"
    state: absent
"""

from ..module_utils.aap_module import AAPModule  # noqa
from ..module_utils.aap_team import AAPTeam  # noqa


def main():
    argument_spec = dict(
        name=dict(type="str", required=True),
        new_name=dict(type="str"),
        description=dict(type="str"),
        organization=dict(type="str", required=True),
        new_organization=dict(type="str"),
        users=dict(type="list"),
        admins=dict(type="list"),
        parents=dict(type="list"),
        state=dict(choices=["present", "absent", "exists", "enforced"], default="present"),
    )

    # Create a module with spec
    module = AAPModule(argument_spec=argument_spec, supports_check_mode=True)

    AAPTeam(module).manage()


if __name__ == "__main__":
    main()
