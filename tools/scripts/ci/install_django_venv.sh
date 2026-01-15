#!/usr/bin/env sh
#
# NOTE: This script is meant to be used by tox as an install_command.
# It handles installing Django dependencies with proper django-ansible-base handling.
#
# Usage: install_django_venv.sh <envname> <pip_opts> <packages>
#
# The script detects Django version from the envname:
#   - py312-django42 -> uses constraints_django42.txt
#   - py312-django52 -> uses constraints_django52.txt
#   - py312 (no suffix) -> uses constraints_django52.txt (default)

# Exit on any error
set -e

# Pass in the tox env name as the first argument
ENV_NAME="$1"
shift  # Remove first argument, rest are pip options and packages from tox

# Determine Django constraint file based on environment name
CONSTRAINT_FILE=""
case "$ENV_NAME" in
    *-django42*)
        CONSTRAINT_FILE="requirements/constraints_django42.txt"
        ;;
    *-django52*|py311|py312)
        CONSTRAINT_FILE="requirements/constraints_django52.txt"
        ;;
esac

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

# Install all dependencies from requirements.txt (includes pinned Django version for production)
pip install psycopg[binary] -r requirements/requirements.txt ${GIT_REQUIREMENTS} "$@"

# If a Django constraint file was determined, reinstall Django to match the constraint.
# This is used for CI testing against different Django versions (e.g., 4.2 vs 5.2)
# while keeping requirements.txt pinned to the production version.
# Note: pip constraints don't override explicit == pins, so we must reinstall explicitly.
if [ -n "$CONSTRAINT_FILE" ] && [ -f "$CONSTRAINT_FILE" ]; then
    echo "Reinstalling Django with constraint file: $CONSTRAINT_FILE"
    pip install --force-reinstall -c "$CONSTRAINT_FILE" Django
    echo "Django version after constraint applied:"
    pip show django | grep Version
fi
