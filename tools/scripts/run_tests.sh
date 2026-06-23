#!/usr/bin/env bash
# Wrapper around pytest that handles JWT keypair generation and cleanup.
#
# Usage (called by tox, not directly):
#   run_tests.sh [pytest args...]
#
# Environment variables (set by tox):
#   PYTEST_NUM_PROCESSES  - xdist worker count (default: auto)
#   GATEWAY_TEST_DIRS     - test directory override (default: aap_gateway_api/tests)
set -euo pipefail

JWT_FILE=$(python tools/scripts/generate_test_jwt_keypair.py)
trap "rm -f $JWT_FILE" EXIT

pytest \
    -n "${PYTEST_NUM_PROCESSES:-auto}" \
    --jwt-keypair-file="$JWT_FILE" \
    --cov=. \
    --cov-report=xml:coverage.xml \
    --cov-report=html \
    --cov-report=json \
    --cov-branch \
    --junit-xml=aap-gateway-test-results.xml \
    ${GATEWAY_TEST_DIRS:-aap_gateway_api/tests} \
    "$@"
