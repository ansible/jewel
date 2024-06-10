#!/usr/bin/python
# coding: utf-8 -*-

# Copyright: (c) 2024, Martin Slemr <@slemrmartin>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)


ANSIBLE_METADATA = {
    "metadata_version": "0.0.1",
    "status": ["preview"],
    "supported_by": "community",
}


DOCUMENTATION = """
---
module: service_key
author: Martin Slemr (@slemrmartin)
short_description: Configure a gateway service key.
description:
    - Configure an automation platform gateway service key.
options:
    name:
      required: true
      type: str
      description: The name of the AAP Service Key, must be unique
    new_name:
      type: str
      description: Setting this option will change the existing name (looked up via the name field)
    is_active:
      type: bool
      description:
      - flag for setting the active state of the Service Key
      - defaults to true by API
    service_cluster:
      description:
      - The name or ID of the Service Cluster
      type: str
    algorithm:
      description:
      - algorithm to use for this Service Key
      choices: ["HS256", "HS384", "HS512"]
    secret:
      type: str
      description:
      - secret to use for this Service Key
      - required when creating new Service Key, non-editable
    secret_length:
      type: int
      description:
        - Number of random bytes in the secret
    mark_previous_inactive:
      type: bool
      description:
        - If true any other secret keys for this service will become inactive

extends_documentation_fragment:
- ansible.gateway_configuration.state
- ansible.gateway_configuration.auth
"""

EXAMPLES = """"""

from ..module_utils.aap_module import AAPModule  # noqa
from ..module_utils.aap_service_key import AAPServiceKey  # noqa


def main():
    argument_spec = dict(
        name=dict(type="str", required=True),
        new_name=dict(type="str"),
        is_active=dict(type="bool"),
        service_cluster=dict(type="str"),
        algorithm=dict(type="str", choices=["HS256", "HS384", "HS512"]),
        secret=dict(type="str"),
        secret_length=dict(type="int"),
        mark_previous_inactive=dict(type="bool"),
        state=dict(type="str", choices=["present", "absent", "exists", "enforced"], default="present"),
    )

    # Create a module with spec
    module = AAPModule(argument_spec=argument_spec, supports_check_mode=True)
    AAPServiceKey(module).manage()


if __name__ == "__main__":
    main()
