#!/usr/bin/env python3
"""
SECURITY NOTICE - MODIFICATIONS MUST BE FROM MAIN REPO BRANCHES
====================================================================
This script accesses secrets (GITHUB_TOKEN) in CI workflows.

⚠️  IMPORTANT: Changes to this script MUST be made from a branch on the
    main repository (ansible/jewel), NOT from a fork.

WHY: The dev-environment.yml workflow replaces this script with the trusted
     base branch version when running PRs from forks to prevent secret
     exfiltration attacks. This means fork PRs cannot test changes to this script.

TO MODIFY THIS SCRIPT:
  1. Get write access to ansible/jewel
  2. Create a branch directly in the main repo (not a fork)
  3. Make your changes and create a PR from that branch
  4. Your changes will be tested in CI since it's not from a fork

See: .github/workflows/dev-environment.yml for the security implementation
====================================================================
"""
import os
import re
import sys

import requests

# --- Configuration ---
COLLECTION_REPO = "ansible/ansible.platform"
GITHUB_API_URL = "https://api.github.com"
# ---


# --- Get CI Environment Variables ---
pr_body = os.environ.get('PR_BODY', '')
# For pull requests, GITHUB_BASE_REF is the base branch (only set on PRs).
# For push events, GITHUB_REF_NAME is the branch name.
current_branch = os.environ.get('GITHUB_BASE_REF') or os.environ.get('GITHUB_REF_NAME')

# --- GitHub Authentication ---
headers = {}
gh_token = os.environ.get('GH_TOKEN')
if gh_token:
    headers['Authorization'] = f"Bearer {gh_token}"

print(f"Headers: {gh_token[0:14]}")


def _clone_repo(repo_url, branch):
    sanitized_url = repo_url
    if repo_url.startswith("https://") and '@' in repo_url:
        sanitized_url = f"https://{repo_url.split('@')[1]}"
    command = f"git clone {repo_url} --depth=1"
    if branch:
        command = f"{command} -b {branch}"
    else:
        branch = "default"
    print(f"Cloning {branch} branch from {sanitized_url} with token '{gh_token[0:14]}'...")
    result = os.popen(command)
    print(result.read())
    termination_status = result.close()
    if termination_status is not None:
        exit_code = os.waitstatus_to_exitcode(termination_status)
        if exit_code == 0:
            print("✅ Cloned repository")
            sys.exit(0)
        else:
            print(f"❌ Error: Git clone failed with return value {exit_code}")
            sys.exit(exit_code)
    else:
        print("Process terminated without a specific exit status (e.g., killed by a signal).")
        sys.exit(1)


# --- Primary Check: Scan PR Body for 'requires' link ---
print("🚀 Starting build process...")
print("Performing primary check: Scanning PR body for a 'requires' link...")
print(f"Scanning body: \"{pr_body[:100]}...\"")

requires_re = re.compile(f'requires.*{COLLECTION_REPO}(?:#|/pull/)([0-9]+)', re.IGNORECASE)
matches = requires_re.search(pr_body)

if matches:
    required_pr = matches.group(1)
    print(f"✅ Found requirement for DAB PR #{required_pr}.")

    pr_url = f'{GITHUB_API_URL}/repos/{COLLECTION_REPO}/pulls/{required_pr}'
    response = requests.get(pr_url, headers=headers)

    if response.status_code == 200:
        pr_data = response.json()
        branch = pr_data['head']['ref']
        repo_url = pr_data['head']['repo']['html_url']

        if not pr_data.get('merged'):
            print(f"Checking out branch '{branch}' from '{repo_url}'...")
            _clone_repo(repo_url, branch)
        else:
            print(f"✅ The referenced PR #{required_pr} has already been merged. No checkout needed.")
    else:
        print(f"❌ Error: Could not fetch data for PR #{required_pr}. Status: {response.status_code}")
        # Continue to secondary check as a fallback
else:
    print("ℹ️ No 'requires' link found in PR body.")

# --- Secondary Check (Fallback): Look for a matching branch ---
print("\nPerforming secondary check: Looking for a matching branch...")
repo_url = f"https://{gh_token}:@github.com/{COLLECTION_REPO}.git"

if current_branch:
    print(f"Current branch detected as '{current_branch}'.")
    print(f"Checking for a matching branch in '{COLLECTION_REPO}'...")

    branch_url = f'{GITHUB_API_URL}/repos/{COLLECTION_REPO}/branches/{current_branch}'
    response = requests.get(branch_url, headers=headers)

    if response.status_code == 200:
        print(f"✅ Success! Found matching branch '{current_branch}' in '{COLLECTION_REPO}'.")
        print(f"Checking out '{current_branch}' from '{repo_url}'...")
        _clone_repo(repo_url, current_branch)
    else:
        print(f"ℹ️ No matching branch found in '{COLLECTION_REPO}'.")
else:
    print("❌️ Could not determine the current branch from CI environment variables.")

print("\nPulling the collection from the default branch...")
_clone_repo(repo_url, None)
