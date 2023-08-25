#!/bin/bash

python3 /scripts/generate_envoy_config.py && envoy -c /etc/envoy/envoy.yaml $@
