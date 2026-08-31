#!/usr/bin/env sh
#
# NOTE: This script is only meant to be used by tox as part of our CI setup.
# The purpose is to install django-ansible-base deps into the tox environment
# iff requirements have changed.

# Pass in the tox env directory as the (only) argument ({envdir}).
# Do not use .tox/<envname> — tox honors TOX_WORK_DIR (CI uses /opt/tox-cache).
ENV_DIR="$1"

DAB_DIR="django-ansible-base"
REQ_FILE="${DAB_DIR}/requirements/requirements_all.txt"
TOX_REQ_FILE="${ENV_DIR}/django_ansible_base_requirements.txt"

# Exit if $DAB_DIR/.git doesn't exist
# In this case, tox will just install from git anyway.
[ ! -d "${DAB_DIR}/.git" ] && exit 0

REQS_CHANGED=0
if [ -f "$TOX_REQ_FILE" ]; then
    diff -q "$REQ_FILE" "$TOX_REQ_FILE" > /dev/null
    REQS_CHANGED=$?
else
    REQS_CHANGED=1
fi

if [ "$REQS_CHANGED" -ne 0 ]; then
    echo "Changes detected in requirements. Installing django-ansible-base..."
    OPTIONAL_DEEPS=`grep '^django-ansible-base\[' requirements/requirements_git.txt | sed 's:^django-ansible-base\[::' | sed 's:\] @.*::'`
    pip install "./${DAB_DIR}/"[$OPTIONAL_DEEPS]
    echo "Caching requirements to avoid needlessly reinstalling..."
    mkdir -p "$ENV_DIR"
    cp "$REQ_FILE" "$TOX_REQ_FILE"
else
    echo "No changes detected in requirements. Skipping django-ansible-base install."
fi
