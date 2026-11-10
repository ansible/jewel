#!/usr/bin/env bash
set -ue

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DAB_DIR="${REPO_ROOT}/django-ansible-base"

ONLY_PACKAGE=""
ONLY_SET=0
USE_LOCAL_DAB=0
TMP_DIR=""

cleanup() {
  if [[ -n "${TMP_DIR}" ]]; then
    rm -rf "${TMP_DIR}"
  fi
}
trap cleanup EXIT

require_uv() {
  if ! command -v uv &>/dev/null; then
    echo "ERROR: uv is required but not found. Install it from https://docs.astral.sh/uv/" >&2
    exit 1
  fi
}

ensure_tmp_dir() {
  if [[ -z "${TMP_DIR}" ]]; then
    TMP_DIR="$(mktemp -d)"
  fi
}

git_requirements_file() {
  if [[ "${USE_LOCAL_DAB}" != "1" ]]; then
    echo "${SCRIPT_DIR}/requirements_git.txt"
    return
  fi
  if [[ ! -d "${DAB_DIR}" ]]; then
    echo "ERROR: local django-ansible-base checkout not found at ${DAB_DIR}" >&2
    exit 1
  fi
  ensure_tmp_dir
  local local_file="${TMP_DIR}/requirements_git.txt"
  local dab_uri
  dab_uri="$(
    python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve().as_uri())' "${DAB_DIR}"
  )"
  while IFS= read -r line || [[ -n "${line}" ]]; do
    if [[ "${line}" == *" @ "* ]]; then
      printf '%s @ %s\n' "${line%% @ *}" "${dab_uri}"
    else
      printf '%s\n' "${line}"
    fi
  done < "${SCRIPT_DIR}/requirements_git.txt" > "${local_file}"
  echo "Using local django-ansible-base from ${DAB_DIR}" >&2
  echo "${local_file}"
}

compile_requirements() {
  require_uv
  local uv_compile="uv pip compile --generate-hashes --python-version=3.12 --no-header --no-strip-extras"
  if [[ "${UV_UPGRADE:-}" == "1" ]]; then
    uv_compile="${uv_compile} --upgrade"
  fi
  if [[ "${USE_LOCAL_DAB}" == "1" ]] || grep -q "@ file://" "${SCRIPT_DIR}/requirements_git.txt"; then
    uv_compile="${uv_compile} --refresh-package django-ansible-base"
  fi
  local output_file="$1"
  local git_requirements
  if [[ "${USE_LOCAL_DAB}" == "1" ]]; then
    ensure_tmp_dir
  fi
  git_requirements="$(git_requirements_file)"
  cd "${SCRIPT_DIR}"

  if [[ -z "${ONLY_PACKAGE}" ]]; then
    ${uv_compile} \
      --no-emit-package django-ansible-base \
      --output-file "${output_file}" \
      requirements.in \
      "${git_requirements}"
    return
  fi

  ensure_tmp_dir
  local resolved_file="${TMP_DIR}/requirements.resolved.txt"
  # Seed the output file so uv treats the current pins as version preferences;
  # otherwise run --only would resolve the whole closure at the latest versions.
  cp "${SCRIPT_DIR}/requirements.txt" "${resolved_file}"
  ${uv_compile} \
    --no-emit-package django-ansible-base \
    --output-file "${resolved_file}" \
    requirements.in \
    "${git_requirements}"
  local filtered_file="${TMP_DIR}/requirements.filtered.txt"
  python3 "${REPO_ROOT}/tools/scripts/filter_requirements_update.py" \
    "${SCRIPT_DIR}/requirements.txt" \
    "${resolved_file}" \
    "${ONLY_PACKAGE}" \
    "${filtered_file}"
  local validated_file="${TMP_DIR}/requirements.validated.txt"
  if ! ${uv_compile} \
    --no-emit-package django-ansible-base \
    --constraints "${filtered_file}" \
    --output-file "${validated_file}" \
    requirements.in \
    "${git_requirements}"; then
    echo "ERROR: selective update produced incompatible requirements; ${output_file} was not changed" >&2
    return 1
  fi
  # Write the curated merge, not validated_file: validation may re-resolve
  # packages outside the selected update.
  cp "${filtered_file}" "${output_file}"
}

usage() {
  cat <<EOF
This script generates requirements.txt from requirements.in

Usage: $0 [run|upgrade|check] [options]

Commands:
  run       Resolve dependencies, only upgrading where required by pins
  upgrade   Upgrade all packages to latest while respecting pins
  check     Verify requirements.txt is in sync with requirements.in

Options:
  --only PACKAGE  Only preserve updates for PACKAGE and its transitive
                  dependencies (available for run and upgrade)
  --local-dab     Resolve against the local django-ansible-base checkout
                  instead of the pinned git reference. Looks for:
                  ${DAB_DIR}
  -h, --help      Show this help
EOF
}

COMMAND=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    run|upgrade|check)
      if [[ -n "${COMMAND}" ]]; then
        echo "ERROR: only one command may be specified" >&2
        usage >&2
        exit 1
      fi
      COMMAND="$1"
      shift
    ;;
    --only)
      if [[ $# -lt 2 || "$2" == -* ]]; then
        echo "ERROR: --only requires a package name" >&2
        exit 1
      fi
      ONLY_PACKAGE="$2"
      ONLY_SET=1
      shift 2
    ;;
    --only=*)
      ONLY_PACKAGE="${1#*=}"
      ONLY_SET=1
      shift
    ;;
    --local-dab)
      USE_LOCAL_DAB=1
      shift
    ;;
    -h|--help)
      usage
      exit 0
    ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 1
    ;;
  esac
done

if [[ -z "${COMMAND}" ]]; then
  usage >&2
  exit 1
fi

if [[ "${ONLY_SET}" == "1" && "${ONLY_PACKAGE}" =~ ^[[:space:]]*$ ]]; then
  echo "ERROR: --only requires a package name" >&2
  exit 1
fi

if [[ "${COMMAND}" == "check" && ( "${ONLY_SET}" == "1" || "${USE_LOCAL_DAB}" == "1" ) ]]; then
  echo "ERROR: --only and --local-dab only apply to run and upgrade" >&2
  exit 1
fi

case "${COMMAND}" in
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
    echo "ERROR: unexpected command: ${COMMAND}" >&2
    usage >&2
    exit 1
  ;;
esac
