#!/usr/bin/env sh
#
# NOTE: This script is only meant to be used by tox as part of our CI setup.
# The purpose is to install django-ansible-base deps into the tox environment
# when requirements have changed, or unconditionally when --force is passed.

# Exit on any error so a failed pip install is never cached as success.
set -e

# Usage: tox-reinstall-django-ansible-base.sh [--force] <envdir>
#
# Pass in the tox env directory as the argument ({envdir}).
# Do not use .tox/<envname> — tox honors TOX_WORK_DIR (CI uses /opt/tox-cache).
# Use --force to bypass the requirements cache, e.g. after installing the
# hashed requirements.txt which may have reverted local DAB dependencies.
FORCE=0
if [ "${1:-}" = "--force" ]; then
    FORCE=1
    shift
fi
ENV_DIR="$1"

DAB_DIR="django-ansible-base"
REQ_FILE="${DAB_DIR}/requirements/requirements_all.txt"
TOX_REQ_FILE="${ENV_DIR}/django_ansible_base_requirements.txt"

# Exit if $DAB_DIR/.git doesn't exist
# In this case, tox will just install from git anyway.
[ ! -d "${DAB_DIR}/.git" ] && exit 0

REQS_CHANGED=0
if [ "$FORCE" -eq 1 ]; then
    REQS_CHANGED=1
elif [ ! -f "$TOX_REQ_FILE" ] || ! diff -q "$REQ_FILE" "$TOX_REQ_FILE" > /dev/null; then
    REQS_CHANGED=1
fi

if [ "$REQS_CHANGED" -ne 0 ]; then
    if [ "$FORCE" -eq 1 ]; then
        echo "Installing local django-ansible-base..."
    else
        echo "Changes detected in requirements. Installing django-ansible-base..."
    fi
    OPTIONAL_DEPS=$(grep '^django-ansible-base\[' requirements/requirements_git.txt | sed 's:^django-ansible-base\[::' | sed 's:\] @.*::')
    DAB_REQUIREMENT="./${DAB_DIR}/"
    if [ -n "$OPTIONAL_DEPS" ]; then
        DAB_REQUIREMENT="${DAB_REQUIREMENT}[$OPTIONAL_DEPS]"
    fi
    # Install the checkout's pinned dependencies (requirements_all.txt)
    # alongside the package itself: the pyproject constraints are loose
    # (e.g. bare 'django-crum'), so without the pins pip would keep whatever
    # the gateway hashed requirements already installed.
    pip install --upgrade -r "$REQ_FILE" "$DAB_REQUIREMENT"
    echo "Caching requirements to avoid needlessly reinstalling..."
    mkdir -p "$ENV_DIR"
    cp "$REQ_FILE" "$TOX_REQ_FILE"
else
    echo "No changes detected in requirements. Skipping django-ansible-base install."
fi
