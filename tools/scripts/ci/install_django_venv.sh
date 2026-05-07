#!/usr/bin/env sh
#
# NOTE: This script is meant to be used by tox as an install_command.
# It handles installing dependencies with proper django-ansible-base handling.
#
# Usage: install_django_venv.sh <envname> <pip_opts> <packages>

# Exit on any error
set -e

# Pass in the tox env name as the first argument
ENV_NAME="$1"
shift  # Remove first argument, rest are pip options and packages from tox

# First, handle django-ansible-base installation
# If this fails, the script will exit due to 'set -e'
./tools/scripts/ci/tox-reinstall-django-ansible-base.sh "$ENV_NAME"

# Check if django-ansible-base was installed from local checkout
# If it was, we don't need to install from git (avoid conflicts)
GIT_REQUIREMENTS=""
if ! pip show django-ansible-base > /dev/null 2>&1; then
    # DAB not installed, so we need to install from git
    GIT_REQUIREMENTS="-r requirements/requirements_git.txt"
fi

# Install all dependencies from requirements.txt (includes pinned Django version)
pip install psycopg[binary] -r requirements/requirements.txt ${GIT_REQUIREMENTS} "$@"
