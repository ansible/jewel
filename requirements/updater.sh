#!/usr/bin/env bash
set -ue

PYTHON=python3.12

for FILE in requirements.in requirements.txt ; do
	if [[ ! -f ${FILE} ]] ; then
		touch ${FILE}
	fi
done
requirements_in="$(readlink -f ./requirements.in)"
requirements_txt="$(readlink -f ./requirements.txt)"
requirements_git="$(readlink -f ./requirements_git.txt)"
pip_compile="pip-compile --no-header --quiet -r --allow-unsafe"

_cleanup() {
  cd /
  [[ "${KEEP_TMP:-0}" = 1 ]] || rm -rf "${_tmp}"
}

generate_requirements() {
  venv="`pwd`/venv"
  echo $venv
  ${PYTHON} -m venv "${venv}"
  # shellcheck disable=SC1090
  source ${venv}/bin/activate

  ${venv}/bin/python -m pip install -U 'pip' pip-tools

  ${pip_compile} "${requirements_in}" "${requirements_git}" --output-file requirements.txt
}

main() {
  base_dir=$(pwd)

  _tmp=$(${PYTHON} -c "import tempfile; print(tempfile.mkdtemp(suffix='.aap-gw-requirements', dir='/tmp'))")

  trap _cleanup INT TERM EXIT

  case $1 in
    "run")
      NEEDS_HELP=0
    ;;
    "upgrade")
      NEEDS_HELP=0
      pip_compile="${pip_compile} --upgrade"
    ;;
    "help")
      NEEDS_HELP=1
    ;;
    *)
      echo ""
      echo "ERROR: Parameter $1 not valid"
      echo ""
      NEEDS_HELP=1
    ;;
  esac 

  if [[ "$NEEDS_HELP" == "1" ]] ; then
    echo "This script generates requirements.txt from requirements.in"
    echo ""
    echo "Usage: $0 [run|upgrade]"
    echo ""
    echo "Commands:"
    echo "help      Print this message"
    echo "run       Run the process only upgrading pinned libraries from requirements.in"
    echo "upgrade   Upgrade all libraries to latest while respecting pinnings"
    echo ""
    exit
  fi

  cp -vf ${requirements_txt} "${_tmp}"
  cd "${_tmp}"

  generate_requirements

  echo "Changing $base_dir to requirements"
  # Strip the django-ansible-base git reference from pip-compile output;
  # it belongs only in requirements_git.txt, but keep its pinned transitives
  awk '/^django-ansible-base/{skip=1; next} /^[^ #]/{skip=0} !skip' requirements.txt \
    | sed "s:$base_dir:requirements:" > "${requirements_txt}"

  _cleanup
}

# set EVAL=1 in case you want to source this script
[[ "${EVAL:-0}" -eq "1" ]] || main "${1:-}"

