#!/usr/bin/env python3
"""
Rewrite gateways default envoy proxy config so that
EDA dev server can co-exist with gateway
"""

import yaml
import sys


def run(input_proxy_file_path, output_proxy_file_path):
    with open(input_proxy_file_path) as f:
        content = yaml.safe_load(f)

    eda = content['services']['eda']
    eda['api_port'] = 8000
    eda['use_tls'] = False

    with open(output_proxy_file_path, "w") as f:
        yaml.dump(content, f)


if __name__ != 'main':
    if len(sys.argv) < 2:
        raise RuntimeError(f"usage: {sys.argv[0]} <input_proxy> <output_proxy>")
    run(sys.argv[1], sys.argv[2])

