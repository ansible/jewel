#!/usr/bin/python
# coding: utf-8 -*-

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
module: service_node
author: Red Hat Contributor (@User)
short_description: Configure a gateway service node.
description:
    - Configure an automation platform gateway service node.
options:
    name:
      required: true
      type: str
      description: The name of the Service Node, must be unique
    new_name:
      type: str
      description: Setting this option will change the existing name (looked up via the name field)
    address:
        description:
            - Network address to route traffic for this service to
            - Must be unique
            - Required when creating new Service Node
        type: str
    service_cluster:
        description:
          - Service Cluster containing this node - name or ID
          - Required when creating new Service Node
        type: str

extends_documentation_fragment:
- ansible.gateway_configuration.state
- ansible.gateway_configuration.auth
"""

EXAMPLES = """
- name: Create service node
  ansible.gateway_configuration.service_node:
    name: "Controller - Node 1"
    address: 10.0.0.1
    service_cluster: controller

- name: Delete service node
  ansible.gateway_configuration.service_node:
    name: "Controller - Node 2"
    state: absent
    name: 3  # ID can be used

- name: Update service node's cluster
  ansible.gateway_configuration.service_node:
    name: "Controller - Node 1"
    address: 10.0.0.1
    service_cluster: 2 # service cluster's name or ID
...
"""

from ..module_utils.aap_module import AAPModule  # noqa
from ..module_utils.aap_service_node import AAPServiceNode  # noqa


def main():
    argument_spec = dict(
        name=dict(type="str", required=True),
        new_name=dict(type="str"),
        address=dict(type="str"),
        service_cluster=dict(type="str"),
        state=dict(choices=["present", "absent", "exists", "enforced"], default="present"),
    )

    # Create a module with spec
    module = AAPModule(argument_spec=argument_spec, supports_check_mode=True)

    # Manage objects through API
    AAPServiceNode(module).manage()


if __name__ == '__main__':
    main()
