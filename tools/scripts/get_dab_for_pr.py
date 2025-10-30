#!/usr/bin/env python3
"""
SECURITY NOTICE - MODIFICATIONS MUST BE FROM MAIN REPO BRANCHES
====================================================================
This script accesses secrets (GH_TOKEN) in CI workflows.

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

import requests  # type: ignore

# --- Configuration ---
DAB_REPO = "ansible/django-ansible-base"
DAB_ENTERPRISE_REPO = "ansible/django-ansible-base"
GITHUB_API_URL = "https://api.github.com"
# ---


def make_github_api_request(url: str, gh_token: str | None, aap_token: str | None) -> requests.Response:
    """
    Make a GitHub API request with appropriate authentication.

    Args:
        url: The GitHub API URL to request
        gh_token: GitHub token for authentication
        aap_token: AAP token for enterprise repo authentication

    Returns:
        Response object (on auth failures, exits with error)
    """
    # Determine if this is an enterprise repo URL
    is_enterprise = DAB_ENTERPRISE_REPO in url

    # Build headers with appropriate token
    if is_enterprise and aap_token:
        headers = {'Authorization': f"Bearer {aap_token}"}
    elif gh_token:
        headers = {'Authorization': f"Bearer {gh_token}"}
    else:
        headers = {}

    # Make the request
    response = requests.get(url, headers=headers)

    # Handle authentication failures
    if response.status_code in [401, 403]:
        print(f"##[error]❌ FATAL: Authentication failed for {url}")
        print(f"##[error]Status code: {response.status_code}")
        sys.exit(1)

    return response


def main():
    # --- Get CI Environment Variables ---
    pr_body = os.environ.get('PR_BODY', '')
    # For pull requests, GITHUB_BASE_REF is the base branch (only set on PRs).
    # For push events, GITHUB_REF_NAME is the branch name.
    current_branch = os.environ.get('GITHUB_BASE_REF') or os.environ.get('GITHUB_REF_NAME')

    # --- GitHub Authentication ---
    gh_token = os.environ.get('GH_TOKEN', None)
    aap_token = os.environ.get('ANSIBLE_TOKEN', None)

    # Variables to hold what we're cloning
    repo_to_clone = None
    branch_to_clone = None

    # =============================================================================
    # PHASE 1: Determine what to clone (repo + branch)
    # =============================================================================

    # --- Primary Check: Scan PR Body for 'requires' link ---
    print("🚀 Starting build process...")
    print("Performing primary check: Scanning PR body for a 'requires' link...")
    print(f"Scanning body: \"{pr_body[:100]}...\"")

    # Match both public and enterprise DAB repos
    requires_re = re.compile(f'requires.*?({DAB_REPO}|{DAB_ENTERPRISE_REPO})(?:#|/pull/)([0-9]+)', re.IGNORECASE)
    matches = requires_re.search(pr_body)

    if matches:
        referenced_repo = matches.group(1).lower()  # Normalize to lowercase for comparison
        required_pr = matches.group(2)
        print(f"✅ Found requirement for DAB PR #{required_pr} in '{referenced_repo}'.")

        # Make API call to get PR details
        pr_url = f'{GITHUB_API_URL}/repos/{referenced_repo}/pulls/{required_pr}'
        response = make_github_api_request(pr_url, gh_token, aap_token)

        if response.status_code != 200:
            print(f"##[error]❌ Error: Could not fetch data for PR #{required_pr}. Status: {response.status_code}")
            print(f"##[error]Explicitly required PR {referenced_repo}#{required_pr} is not accessible")
            sys.exit(1)  # Hard failure - they specified a specific PR that doesn't work

        pr_data = response.json()

        if not pr_data.get('merged'):
            # PR is still open - clone the PR branch
            branch_to_clone = pr_data['head']['ref']
            repo_to_clone = pr_data['head']['repo']['full_name']
            print(f"✅ Will clone branch '{branch_to_clone}' from '{repo_to_clone}'")
        else:
            # PR is merged - clone the base branch that contains the merged changes
            branch_to_clone = pr_data['base']['ref']
            repo_to_clone = pr_data['base']['repo']['full_name']
            print(f"✅ The referenced PR #{required_pr} has already been merged into '{branch_to_clone}'.")
            print(f"Will clone the base branch '{branch_to_clone}' from '{repo_to_clone}'.")

    # If we haven't found something to clone yet, check for matching branch
    if not repo_to_clone and current_branch:
        # --- Secondary Check (Fallback): Look for a matching branch ---
        # If we're here, matches must be False (otherwise repo_to_clone would be set)
        print("ℹ️ No 'requires' link found in PR body.")
        print("\nPerforming secondary check: Looking for a matching branch...")
        print(f"Current branch detected as '{current_branch}'.")

        # Always check in this order: public repo first, then enterprise
        for repo in [DAB_REPO, DAB_ENTERPRISE_REPO]:
            print(f"Checking for branch '{current_branch}' in '{repo}'...")

            branch_url = f'{GITHUB_API_URL}/repos/{repo}/branches/{current_branch}'
            response = make_github_api_request(branch_url, gh_token, aap_token)

            if response.status_code == 200:
                print(f"✅ Success! Found matching branch '{current_branch}' in '{repo}'.")
                repo_to_clone = repo
                branch_to_clone = current_branch
                break
            elif response.status_code == 404:
                print(f"ℹ️ Branch '{current_branch}' not found in '{repo}', trying next repository...")
            else:
                # Any other error (403, 500, etc.) is a hard failure
                print(f"##[error]❌ FATAL: Unexpected error checking {repo}")
                print(f"##[error]Status code: {response.status_code}")
                sys.exit(1)

    # If we still don't have something to clone, we've exhausted all options
    if not repo_to_clone:
        print("##[error]❌ FATAL: Could not find DAB branch to clone")
        sys.exit(1)

    # =============================================================================
    # PHASE 2: Perform the clone with authentication
    # =============================================================================

    # At this point, repo_to_clone and branch_to_clone are guaranteed to be set
    print(f"\n🔧 Preparing to clone '{branch_to_clone}' from '{repo_to_clone}'...")

    # Determine the authenticated clone URL (use same token precedence as API calls)
    if DAB_ENTERPRISE_REPO in repo_to_clone and aap_token:
        clone_url = f"https://{aap_token}@github.com/{repo_to_clone}.git"
        print("Using ANSIBLE_TOKEN for enterprise repo clone...")
    elif gh_token:
        clone_url = f"https://{gh_token}@github.com/{repo_to_clone}.git"
    else:
        clone_url = f"https://github.com/{repo_to_clone}.git"

    # Perform the clone
    clone_cmd = f'git clone {clone_url} -b {branch_to_clone} --depth=1 django-ansible-base'
    masked_cmd = re.sub(r'//[^@]+@', '//***@', clone_cmd)
    print(f"Executing: {masked_cmd}")
    exit_code = os.system(clone_cmd)

    if exit_code == 0:
        print("✅ Successfully cloned django-ansible-base")
        sys.exit(0)
    else:
        print(f"##[error]❌ FATAL: git clone failed with exit code {exit_code}")
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
