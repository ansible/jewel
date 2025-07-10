#!/usr/bin/env python3
import os
import re
import sys

import requests

# --- Configuration ---
DAB_REPO = "ansible/django-ansible-base"
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

# --- Primary Check: Scan PR Body for 'requires' link ---
print("🚀 Starting build process...")
print("Performing primary check: Scanning PR body for a 'requires' link...")
print(f"Scanning body: \"{pr_body[:100]}...\"")

requires_re = re.compile(f'requires.*{DAB_REPO}(?:#|/pull/)([0-9]+)', re.IGNORECASE)
matches = requires_re.search(pr_body)

if matches:
    required_pr = matches.group(1)
    print(f"✅ Found requirement for DAB PR #{required_pr}.")

    pr_url = f'{GITHUB_API_URL}/repos/{DAB_REPO}/pulls/{required_pr}'
    response = requests.get(pr_url, headers=headers)

    if response.status_code == 200:
        pr_data = response.json()
        branch = pr_data['head']['ref']
        repo_url = pr_data['head']['repo']['html_url']

        if not pr_data.get('merged'):
            print(f"Checking out branch '{branch}' from '{repo_url}'...")
            os.system(f'git clone {repo_url} -b {branch} --depth=1')
            sys.exit(0)  # Exit successfully
        else:
            print(f"✅ The referenced PR #{required_pr} has already been merged. No checkout needed.")
    else:
        print(f"❌ Error: Could not fetch data for PR #{required_pr}. Status: {response.status_code}")
        # Continue to secondary check as a fallback
else:
    print("ℹ️ No 'requires' link found in PR body.")

# --- Secondary Check (Fallback): Look for a matching branch ---
print("\nPerforming secondary check: Looking for a matching branch...")

if current_branch:
    print(f"Current branch detected as '{current_branch}'.")
    print(f"Checking for a matching branch in '{DAB_REPO}'...")

    branch_url = f'{GITHUB_API_URL}/repos/{DAB_REPO}/branches/{current_branch}'
    response = requests.get(branch_url, headers=headers)

    if response.status_code == 200:
        print(f"✅ Success! Found matching branch '{current_branch}' in '{DAB_REPO}'.")
        repo_url = f"https://github.com/{DAB_REPO}.git"
        print(f"Checking out '{current_branch}' from '{repo_url}'...")
        os.system(f'git clone {repo_url} -b {current_branch} --depth=1')
    else:
        print(f"ℹ️ No matching branch found in '{DAB_REPO}'.")
else:
    print("Could not determine the current branch from CI environment variables.")
