#!/usr/bin/env bash
set -ue

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

require_uv() {
  if ! command -v uv &>/dev/null; then
    echo "ERROR: uv is required but not found. Install it from https://docs.astral.sh/uv/" >&2
    exit 1
  fi
}

compile_requirements() {
  require_uv
  local uv_compile="uv pip compile --generate-hashes --python-version=3.12 --no-header"
  if [[ "${UV_UPGRADE:-}" == "1" ]]; then
    uv_compile="${uv_compile} --upgrade"
  fi
  local output_file="$1"
  cd "${SCRIPT_DIR}"
  ${uv_compile} \
    --no-emit-package django-ansible-base \
    --output-file "${output_file}" \
    requirements.in \
    requirements_git.txt
}

case "${1:-}" in
  "run")
    compile_requirements requirements.txt
  ;;
  "upgrade")
    UV_UPGRADE=1 compile_requirements requirements.txt
  ;;
  "check")
    python3 "${SCRIPT_DIR}/../tools/scripts/check_requirements.py"
  ;;
  *)
    echo "This script generates requirements.txt from requirements.in"
    echo ""
    echo "Usage: $0 [run|upgrade|check]"
    echo ""
    echo "Commands:"
    echo "  run       Resolve dependencies, only upgrading where required by pins"
    echo "  upgrade   Upgrade all packages to latest while respecting pins"
    echo "  check     Verify requirements.txt is in sync with requirements.in"
    echo ""
    exit 1
  ;;
esac
