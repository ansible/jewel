# -*- coding: utf-8 -*-
# Apache-2.0

from __future__ import absolute_import, division, print_function

__metaclass__ = type


class ModuleDocFragment(object):
    # Ansible Galaxy documentation fragment
    DOCUMENTATION = r"""
options:
    state:
      description:
        - Desired state of the resource.
        - Enforced state C(enforced) will default values of any option not provided.
      choices: ["present", "absent", "exists", "enforced"]
      default: "present"
      type: str
"""
