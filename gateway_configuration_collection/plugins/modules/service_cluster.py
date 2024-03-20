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
module: service_cluster
author: Red Hat Contributor (@User)
short_description: Configure a gateway service cluster.
description:
    - Configure an automation platform gateway service cluster.
options:
    name:
      required: true
      type: str
      description: The name of the Ansible service, must be unique
    new_name:
      type: str
      description: Setting this option will change the existing name (looked up via the name field)
    service_type:
      description:
        - Type of the Ansible service
        - Required when creating new Service Cluster
      choices: ["hub", "controller", "eda", "gateway"]
      type: str

extends_documentation_fragment:
- ansible.gateway_configuration.state
- ansible.gateway_configuration.auth
"""


EXAMPLES = """
- name: Add service cluster
  ansible.gateway_configuration.service_cluster:
    name: Automation Controller
    service_type: controller
    state: present

- name: Delete service cluster
  ansible.gateway_configuration.service_cluster:
    name: Automation Controller
    state: absent

- name: Check if cluster exists
  ansible.gateway_configuration.service_cluster:
    name: Automation Controller
    state: exists
...
"""

from ..module_utils.aap_module import AAPModule  # noqa
from ..module_utils.aap_service_cluster import AAPServiceCluster  # noqa


def main():
    # Any additional arguments that are not fields of the item can be added here
    argument_spec = dict(
        name=dict(required=True, type='str'),
        new_name=dict(type='str'),
        service_type=dict(type="str", choices=["hub", "controller", "eda", "gateway"]),
        state=dict(choices=["present", "absent", "exists", "enforced"], default="present"),
    )

    # Create a module with spec
    module = AAPModule(argument_spec=argument_spec, supports_check_mode=True)

    # Manage objects through API
    AAPServiceCluster(module).manage()


if __name__ == "__main__":
    main()
