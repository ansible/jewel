#!/usr/bin/env python3
"""
Unified PR-based Repository Checkout Script

SECURITY NOTICE - MODIFICATIONS MUST BE FROM MAIN REPO BRANCHES
====================================================================
This script accesses secrets (tokens) in CI workflows.

⚠️  IMPORTANT: Changes to this script MUST be made from a branch on the
    main repository (ansible/jewel), NOT from a fork.

WHY: Workflows replace this script with the trusted base branch version when
     running PRs from forks to prevent secret exfiltration attacks. This means
     fork PRs cannot test changes to this script.

TO MODIFY THIS SCRIPT:
  1. Get write access to ansible/jewel
  2. Create a branch directly in the main repo (not a fork)
  3. Make your changes and create a PR from that branch
  4. Your changes will be tested in CI since it's not from a fork

See: .github/workflows/*.yml for the security implementation
====================================================================

Usage Examples:
    # Basic - clone DAB with enterprise fallback for devel
    python get_pr_checkout.py \\
      --always-clone-repos ansible/django-ansible-base

    # Dev environment (needs DAB + collection)
    python get_pr_checkout.py \\
      --always-clone-repos ansible/django-ansible-base \\
      --always-clone-repos ansible/ansible.platform

    # With explicit PR requirements in PR body:
    # "Requires ansible/django-ansible-base#45"
    # "Requires: ansible/ansible.platform#67, other-org/other-repo#89"

Repository Specification Format:
    --always-clone-repos accepts "[org1|org2|...]/repo-name" format:
    - Tries each org in order until finding one with the target branch
    - All variants share the same repo name (and thus target directory)
    - For devel: falls back to default branch if no match found
    

    Example: ansible/django-ansible-base
    - Tries ansible/django-ansible-base first
    - Falls back to ansible/django-ansible-base if enterprise doesn't have the branch
    - Always clones to "django-ansible-base/" directory
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from typing import Dict, Optional, Tuple

import requests  # type: ignore

GITHUB_API_URL = "https://api.github.com"


def parse_all_github_pr_references(pr_body: str) -> list:
    """
    Extract GitHub PR references that are marked as requirements from PR body.

    Looks for "requires" keyword followed by GitHub PR references.
    Supports multiple formats:
    - requires org/repo#123
    - Requires: https://github.com/org/repo/pull/123
    - Multiple per line with any separator: Requires org/repo#1, org/repo#2
    - Multiple requires lines

    Returns:
        List of strings in format 'org/repo#pr_num' (normalized to lowercase)
    """
    result = []

    # Find all "requires" statements (case-insensitive)
    # Extract everything from "requires" to end of line or next "requires"
    requires_pattern = re.compile(r'requires[^\n]*', re.IGNORECASE)

    for requires_match in requires_pattern.finditer(pr_body):
        requires_text = requires_match.group(0)

        # Define regex components for clarity
        org = r'[a-zA-Z0-9_-]+'
        repo = r'[a-zA-Z0-9_.-]+'
        org_repo = f'{org}/{repo}'
        pr_num = r'\d+'

        # Optional GitHub URL prefix
        gh_prefix = r'https?://github\.com/'

        # Separator between repo and PR number (either /pull/ or #)
        separator = r'/pull/|#'

        # Full pattern: optional URL prefix, org/repo (captured), separator, PR number (captured)
        pr_pattern = re.compile(f'(?:{gh_prefix})?({org_repo})(?:{separator})({pr_num})')

        for repo, pr_num in pr_pattern.findall(requires_text):
            # Normalize repo name (lowercase, strip .git)
            result.append(f"{get_normalized_repo(repo)}#{pr_num}")

    return result


def make_api_request(path: str, token: Optional[str], context: str = "") -> Optional[Dict]:
    """
    Make a GitHub API request with authentication and error handling.

    Args:
        path: API path (e.g., '/repos/org/repo/pulls/123')
        token: Optional GitHub authentication token
        context: Optional context string for error messages (e.g., 'repo#123')

    Returns:
        Parsed JSON response dict on success, None on error
    """
    url = f'{GITHUB_API_URL}{path}'
    headers = {}
    if token:
        headers['Authorization'] = f"Bearer {token}"

    response = requests.get(url, headers=headers)

    if response.status_code == 401 or response.status_code == 403:
        print(f"##[error]❌ FATAL: Authentication failed{f' for {context}' if context else ''}")
        print(f"##[error]Status code: {response.status_code}")
        return None

    if response.status_code != 200:
        print(f"##[error]❌ FATAL: API request failed{f' for {context}' if context else ''}")
        print(f"##[error]Status code: {response.status_code}")
        print(f"##[error]Path: {path}")
        return None

    return response.json()


def extract_branch_from_pr(pr_data: dict) -> Tuple[str, str]:
    """
    Extract branch name and repository from PR data (handles open and merged PRs).

    Args:
        pr_data: PR data from GitHub API

    Returns:
        Tuple of (branch_name, repo_full_name)
    """
    # PR is merged -> use base branch; PR is open -> use head branch from fork
    is_merged = pr_data.get("merged")
    source = "base" if is_merged else "head"
    branch = pr_data[source]["ref"]
    repo_full_name = pr_data[source]["repo"]["full_name"]

    # Print informative message
    pr_num = pr_data.get("number", "")
    if is_merged:
        print(f"ℹ️  PR #{pr_num} is merged, cloning base branch '{branch}' from '{repo_full_name}'")
    else:
        print(f"ℹ️  PR #{pr_num} is open, cloning branch '{branch}' from '{repo_full_name}'")

    return branch, repo_full_name


def build_clone_url(repo_full_name: str, token: Optional[str]) -> str:
    """Construct an authenticated git clone URL."""
    token_part = f'{token}@' if token else ''
    return f"https://{token_part}github.com/{repo_full_name}.git"


def mask_token_in_url(url: str) -> str:
    """Mask authentication tokens in URLs for safe logging."""
    return re.sub(r'//[^@]+@', '//***@', url)


def execute_git_clone(repo_url: str, branch: Optional[str], target_dir: str) -> bool:
    """
    Execute a git clone command with proper error handling.

    Returns:
        True if successful, False otherwise
    """
    # Check if git is available
    if not shutil.which('git'):
        print("##[error]❌ FATAL: git command not found")
        print("##[error]Please ensure git is installed and available in PATH")
        return False

    # Build git clone command
    cmd = ['git', 'clone', repo_url, '--depth=1']
    if branch:
        cmd.extend(['-b', branch])
    cmd.append(target_dir)

    # Mask token in command for logging
    masked_cmd = ' '.join(cmd)
    masked_cmd = mask_token_in_url(masked_cmd)
    print(f"Executing: {masked_cmd}")

    # Execute git clone and capture output
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print(f"✅ Successfully cloned {target_dir}")
        return True
    else:
        print(f"##[error]❌ Git clone failed with exit code {result.returncode}")
        if result.stderr:
            print("##[error]")
            print("##[error]Git error output:")
            for line in result.stderr.strip().split('\n'):
                # Mask any tokens that might appear in error messages
                masked_line = mask_token_in_url(line)
                print(f"##[error]  {masked_line}")
        return False


def get_normalized_repo(repo: str) -> str:
    """
    lower and rstrip the repo

    Returns a string with normalized repo.
    """
    # Normalize repo
    return repo.lower().rstrip('.git')


def branch_exists(repo: str, branch: str, token: Optional[str]) -> bool:
    """Check if a branch exists in a repository."""
    result = make_api_request(f'/repos/{repo}/branches/{branch}', token)
    return result is not None


def parse_and_validate_repo_specs(repo_specs: list) -> list:
    """
    Parse and validate --always-clone-repos arguments.

    Returns:
        List of variant lists. Each variant list contains normalized repo strings.
        Example: [['org1/repo', 'org2/repo'], ['org3/other']]
    """
    invalid_repos = []
    always_clone_repos = []

    # Regex to match [org1|org2]/repo-name or org/repo-name
    repo_pattern = re.compile(r'^(?:\[([a-zA-Z0-9_-]+(?:\|[a-zA-Z0-9_-]+)+)\]/|([a-zA-Z0-9_-]+)/)([a-zA-Z0-9_.-]+)$')

    for repo_spec in repo_specs:
        match = repo_pattern.match(repo_spec)
        if not match:
            invalid_repos.append(repo_spec)
        else:
            org_list_str, single_org, repo_name = match.groups()

            if org_list_str:
                # Multiple orgs: [org1|org2]/repo-name
                orgs = org_list_str.split('|')
                repo_variants = [f"{org}/{repo_name}" for org in orgs]
                always_clone_repos.append([get_normalized_repo(r) for r in repo_variants])
            else:
                # Single org: org/repo-name
                always_clone_repos.append([get_normalized_repo(f"{single_org}/{repo_name}")])

    if invalid_repos:
        print("##[error]❌ FATAL: Invalid repository format(s)")
        for repo in invalid_repos:
            print(f"##[error]  - '{repo}'")
        print("##[error]")
        print("##[error]Repository must be in 'org/name' or '[org1|org2]/name' format")
        print("##[error]Examples:")
        print("##[error]  - ansible/django-ansible-base")
        print("##[error]  - ansible/django-ansible-base")
        sys.exit(1)

    return always_clone_repos


def get_env_config():
    """Get and validate environment configuration."""
    pr_body = os.environ.get('PR_BODY', '')
    target_branch = os.environ.get('GITHUB_BASE_REF') or os.environ.get('GITHUB_REF_NAME')
    token = os.environ.get('GH_TOKEN') or os.environ.get('ANSIBLE_TOKEN')

    print(f"Target branch: {target_branch or 'unknown'}")
    print(f"Token available: {'yes' if token else 'no'}")

    if not target_branch:
        print("##[error]❌ FATAL: Could not determine target branch from CI environment")
        print("##[error]")
        print("##[error]Expected one of these environment variables to be set:")
        print("##[error]  - GITHUB_BASE_REF (for pull requests)")
        print("##[error]  - GITHUB_REF_NAME (for branch pushes)")
        print("##[error]")
        print("##[error]Cannot proceed without knowing the target branch to avoid")
        print("##[error]cloning incorrect dependency versions.")
        sys.exit(1)

    return pr_body, target_branch, token


def process_explicit_requirements(pr_body: str, token: Optional[str]) -> list:
    """Process explicit PR requirements from PR body."""
    explicit_requirements = parse_all_github_pr_references(pr_body)
    repos_to_clone = []

    print(f"✅ Found {len(explicit_requirements)} explicit requirement(s) in PR body:")
    errors = False

    for requirement in explicit_requirements:
        repo, pr_num = requirement.split('#')
        print(f"  - {requirement}")
        target_dir = repo.split('/')[-1]

        pr_data = make_api_request(f"/repos/{repo}/pulls/{pr_num}", token, context=f"{repo}#{pr_num}")
        if pr_data is None:
            print(f"##[error]Explicitly required PR {requirement} is not accessible")
            errors = True
            continue

        branch, repo_full_name = extract_branch_from_pr(pr_data)

        repos_to_clone.append(
            {
                'target_dir': target_dir,
                'branch': branch,
                'clone_url': build_clone_url(repo_full_name, token),
                'repo': repo,
            }
        )

    if errors:
        print("\n##[error]Errors found in explicit requirements, exiting...")
        sys.exit(1)

    return repos_to_clone


def process_always_clone_repos(always_clone_repos: list, target_branch: str, token: Optional[str], repos_to_clone: list) -> None:
    """Process always-clone repos and add them to repos_to_clone list."""
    print(f"\nProcessing {len(always_clone_repos)} always-clone repo(s):")
    errors = False

    for repo_variants in always_clone_repos:
        primary_repo = repo_variants[0]
        target_dir = primary_repo.split('/')[-1]

        # Skip if already in list from explicit requirement
        if any(item['repo'] in repo_variants for item in repos_to_clone):
            print(f"  ⏭️  Skipping {primary_repo} - already in list from explicit requirement")
            continue

        # Try to find a variant with the matching branch
        matching_repo = None
        for repo_variant in repo_variants:
            print(f"  Checking for branch '{target_branch}' in '{repo_variant}'...")
            if branch_exists(repo_variant, target_branch, token):
                print(f"  ✅ Found matching branch '{target_branch}' in '{repo_variant}'")
                matching_repo = repo_variant
                break
            else:
                print(f"  ℹ️  Branch '{target_branch}' not found in '{repo_variant}'")

        if matching_repo:
            print(f"  + Adding {matching_repo}")
            repos_to_clone.append(
                {
                    'target_dir': target_dir,
                    'branch': target_branch,
                    'clone_url': build_clone_url(matching_repo, token),
                    'repo': matching_repo,
                }
            )
        else:
            print(f"##[error]❌ FATAL: No branch {target_branch} found in {repo_variants}")
            errors = True

    if errors:
        print("##[error]")
        print("##[error]Cannot proceed without knowing the target branch to avoid")
        print("##[error]cloning incorrect dependency versions.")
        sys.exit(1)


def validate_no_duplicate_directories(repos_to_clone: list) -> dict:
    """Validate no duplicate target directories. Returns dir_sources dict."""
    print("\n" + "=" * 70)
    print("STEP 2: Validating repository list")
    print("=" * 70)

    dir_sources = {}
    for item in repos_to_clone:
        target_dir = item['target_dir']
        if target_dir not in dir_sources:
            dir_sources[target_dir] = []
        dir_sources[target_dir].append(item)

    errors = False
    for target_dir in dir_sources.keys():
        if len(dir_sources[target_dir]) > 1:
            if not errors:
                print("##[error]❌ FATAL: Duplicate target directories detected")
                print("##[error]")
            print(f"##[error]Directory: {target_dir}")
            print("##[error]The following repositories would clone to the same directory:")
            for item in dir_sources[target_dir]:
                print(f"##[error]  - {item['repo']}")
            errors = True

    if errors:
        print("##[error]")
        print("##[error]Cannot clone multiple repositories to the same directory.")
        print("##[error]Please remove duplicate requirements.")
        sys.exit(1)

    print(f"✅ Validation passed - {len(dir_sources.keys())} unique repository(ies) to clone")
    return dir_sources


def clone_all_repos(dir_sources: dict) -> list:
    """Clone all repositories. Returns list of successfully cloned repos."""
    print("\n" + "=" * 70)
    print("STEP 3: Cloning repositories")
    print("=" * 70)

    cloned_repos = []
    errors = False

    for target_dir, items in dir_sources.items():
        item = items[0]

        print(f"\n📦 Cloning {item['repo']} to {target_dir}")
        if execute_git_clone(item['clone_url'], item['branch'], item['target_dir']):
            cloned_repos.append(item['repo'])
        else:
            print(f"##[error]❌ FATAL: Failed to clone {item['repo']}")
            errors = True

    if errors:
        sys.exit(1)

    return cloned_repos


def main():
    parser = argparse.ArgumentParser(
        description='Clone repositories based on PR requirements or branch matching',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='See script docstring for usage examples',
    )
    parser.add_argument(
        '--always-clone-repos',
        action='append',
        default=[],
        help='Repository that must be cloned (repeatable). Format: [org1|org2]/repo-name. Example: ansible/django-ansible-base',
    )

    args = parser.parse_args()

    # Parse and validate repo specs
    always_clone_repos = parse_and_validate_repo_specs(args.always_clone_repos)

    # Get environment configuration
    pr_body, target_branch, token = get_env_config()

    # Show startup info
    print("🚀 Starting repository checkout process...")
    if always_clone_repos:
        print("Always-clone repos:")
        for variants in always_clone_repos:
            if len(variants) > 1:
                print(f"  - {variants[0]} (with {len(variants) - 1} alternate(s))")
            else:
                print(f"  - {variants[0]}")

    # STEP 1: Build list of repos to clone
    print("\n" + "=" * 70)
    print("STEP 1: Building list of repositories to clone")
    print("=" * 70)

    repos_to_clone = process_explicit_requirements(pr_body, token)
    process_always_clone_repos(always_clone_repos, target_branch, token, repos_to_clone)

    # STEP 2: Validate no duplicates
    dir_sources = validate_no_duplicate_directories(repos_to_clone)

    # STEP 3: Clone all repos
    cloned_repos = clone_all_repos(dir_sources)

    print("\n" + "=" * 70)
    print("✅ All repositories cloned successfully!")
    print("=" * 70)
    print(f"Total repositories cloned: {len(cloned_repos)}")
    for repo in sorted(cloned_repos):
        print(f"  ✓ {repo}")

    sys.exit(0)


if __name__ == "__main__":
    main()
