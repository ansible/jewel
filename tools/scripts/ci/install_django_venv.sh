#!/usr/bin/env sh
#
# NOTE: This script is meant to be used by tox as an install_command.
# It handles installing dependencies with proper django-ansible-base handling.
#
# Usage: install_django_venv.sh <envdir> <pip_opts> <packages>

# Exit on any error
set -e

# Pass in the tox env directory as the first argument ({envdir})
ENV_DIR="$1"
shift  # Remove first argument, rest are pip options and packages from tox

DAB_DIR="django-ansible-base"
HAS_LOCAL_DAB=0
if [ -d "${DAB_DIR}/.git" ]; then
    HAS_LOCAL_DAB=1
fi

# Install hashed production requirements separately so pip's --require-hashes
# mode does not conflict with unhashed test/dev dependencies.
pip install --require-hashes --no-cache-dir -r requirements/requirements.txt

# If a local django-ansible-base checkout is present, skip the git requirement
# and install the checkout after the hashed requirements below. This makes the
# checked-out branch's dependencies win over versions pinned for DAB devel.
GIT_REQUIREMENTS=""
if [ "$HAS_LOCAL_DAB" -eq 0 ]; then
    GIT_REQUIREMENTS="-r requirements/requirements_git.txt"
fi

pip install 'psycopg[binary]' ${GIT_REQUIREMENTS} "$@"

if [ "$HAS_LOCAL_DAB" -eq 1 ]; then
    # --force bypasses the cache so DAB dependencies are re-applied over the
    # hashed requirements that were just installed.
    ./tools/scripts/ci/tox-reinstall-django-ansible-base.sh --force "$ENV_DIR"
fi
