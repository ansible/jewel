#!/usr/bin/env python3
"""
Integration tests for get_pr_checkout.py (unified PR checkout script)

Run with:
    pytest tools/scripts/tests/test_get_pr_checkout.py -v --cov=tools/scripts/get_pr_checkout --cov-report=term-missing
"""

import os
import sys
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

# Add parent directory to path so we can import the script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import get_pr_checkout  # noqa: E402


class MockResponse:
    """Mock requests.Response object"""

    def __init__(self, status_code: int, json_data: Optional[Dict[str, Any]] = None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self):
        return self._json_data


def _set_cli_args(*repos, enable_enterprise=False):
    """Helper to set sys.argv for testing"""
    sys.argv = ["get_pr_checkout.py"]
    for repo in repos:
        sys.argv.extend(["--always-clone-repos", repo])
    if enable_enterprise:
        sys.argv.append("--enable-enterprise")


class TestParseGitHubPRReferences:
    """Test parsing of GitHub PR references from PR body"""

    def test_single_shorthand_format(self):
        """Test parsing single shorthand format"""
        pr_body = "Requires ansible/django-ansible-base#123"
        refs = get_pr_checkout.parse_all_github_pr_references(pr_body)

        assert refs == ["ansible/django-ansible-base#123"]

    def test_single_url_format(self):
        """Test parsing single full URL format"""
        pr_body = "Requires https://github.com/ansible/django-ansible-base/pull/456"
        refs = get_pr_checkout.parse_all_github_pr_references(pr_body)

        assert refs == ["ansible/django-ansible-base#456"]

    def test_multiple_formats_same_line(self):
        """Test parsing multiple formats on same line"""
        pr_body = "Requires ansible/django-ansible-base#123, https://github.com/ansible/ansible.platform/pull/456"
        refs = get_pr_checkout.parse_all_github_pr_references(pr_body)

        assert set(refs) == {"ansible/django-ansible-base#123", "ansible/ansible.platform#456"}

    def test_multiple_lines(self):
        """Test parsing multiple lines"""
        pr_body = """
        Requires ansible/django-ansible-base#123
        Requires: ansible/ansible.platform#456
        """
        refs = get_pr_checkout.parse_all_github_pr_references(pr_body)

        assert set(refs) == {"ansible/django-ansible-base#123", "ansible/ansible.platform#456"}

    def test_various_separators(self):
        """Test parsing with various separators"""
        pr_body = "Requires: ansible/repo1#1; ansible/repo2#2, ansible/repo3#3"
        refs = get_pr_checkout.parse_all_github_pr_references(pr_body)

        assert set(refs) == {"ansible/repo1#1", "ansible/repo2#2", "ansible/repo3#3"}

    def test_case_insensitive(self):
        """Test case-insensitive matching"""
        pr_body = "REQUIRES Ansible/Django-Ansible-Base#789"
        refs = get_pr_checkout.parse_all_github_pr_references(pr_body)

        assert refs == ["ansible/django-ansible-base#789"]

    def test_no_matches(self):
        """Test when no matches found"""
        pr_body = "This is a regular PR description with no requirements"
        refs = get_pr_checkout.parse_all_github_pr_references(pr_body)

        assert refs == []

    def test_duplicate_repos_same_line(self):
        """Test that duplicate repos on same line are returned (validation happens in main)"""
        pr_body = "Requires ansible/django-ansible-base#123, ansible/django-ansible-base#456"
        refs = get_pr_checkout.parse_all_github_pr_references(pr_body)

        # Parser doesn't validate duplicates, just returns both
        assert len(refs) == 2
        assert "ansible/django-ansible-base#123" in refs
        assert "ansible/django-ansible-base#456" in refs

    def test_duplicate_repos_different_lines(self):
        """Test that duplicate repos on different lines are returned (validation happens in main)"""
        pr_body = """
        Requires ansible/django-ansible-base#123
        Requires ansible/django-ansible-base#456
        """
        refs = get_pr_checkout.parse_all_github_pr_references(pr_body)

        # Parser doesn't validate duplicates, just returns both
        assert len(refs) == 2
        assert "ansible/django-ansible-base#123" in refs
        assert "ansible/django-ansible-base#456" in refs

    def test_enterprise_repo(self):
        """Test parsing enterprise repo reference"""
        pr_body = "Requires ansible/django-ansible-base#789"
        refs = get_pr_checkout.parse_all_github_pr_references(pr_body)

        assert refs == ["ansible/django-ansible-base#789"]

    def test_ignores_non_requires_references(self):
        """Test that non-requires PR references are ignored"""
        pr_body = """
        This PR replaces ansible/jewel#843
        Because of django/django#54390 we have to make this change
        See also kubernetes/kubernetes#12345 for context
        Fixes ansible/ansible#98765
        """
        refs = get_pr_checkout.parse_all_github_pr_references(pr_body)

        # Should find nothing since none have "requires"
        assert refs == []

    def test_requires_with_other_references(self):
        """Test that only requires references are matched when mixed with others"""
        pr_body = """
        Replaces ansible/jewel#843
        Requires ansible/django-ansible-base#123
        See also kubernetes/kubernetes#12345
        """
        refs = get_pr_checkout.parse_all_github_pr_references(pr_body)

        # Should only find the one with "requires"
        assert refs == ["ansible/django-ansible-base#123"]

    def test_multiple_requires_ignores_other_references(self):
        """Test multiple requires with non-requires mixed in"""
        pr_body = """
        This fixes ansible/ansible#98765
        Requires: ansible/django-ansible-base#123
        Based on django/django#54390
        Requires ansible/ansible.platform#456
        Replaces ansible/jewel#999
        """
        refs = get_pr_checkout.parse_all_github_pr_references(pr_body)

        # Should only find the two with "requires"
        assert set(refs) == {"ansible/django-ansible-base#123", "ansible/ansible.platform#456"}


class TestHelperFunctions:
    """Test helper utility functions"""

    def test_extract_branch_from_pr_open(self):
        """Test extracting branch from open PR"""
        pr_data = {"number": 123, "merged": False, "head": {"ref": "feature-branch", "repo": {"full_name": "user/django-ansible-base"}}}

        branch, repo = get_pr_checkout.extract_branch_from_pr(pr_data)
        assert branch == "feature-branch"
        assert repo == "user/django-ansible-base"

    def test_extract_branch_from_pr_merged(self):
        """Test extracting branch from merged PR"""
        pr_data = {"number": 456, "merged": True, "base": {"ref": "devel", "repo": {"full_name": "ansible/django-ansible-base"}}}

        branch, repo = get_pr_checkout.extract_branch_from_pr(pr_data)
        assert branch == "devel"
        assert repo == "ansible/django-ansible-base"

    def test_build_clone_url_with_token(self):
        """Test building authenticated clone URL"""
        url = get_pr_checkout.build_clone_url("ansible/django-ansible-base", "test_token")
        assert url == "https://test_token@github.com/ansible/django-ansible-base.git"

    def test_build_clone_url_without_token(self):
        """Test building unauthenticated clone URL"""
        url = get_pr_checkout.build_clone_url("ansible/django-ansible-base", None)
        assert url == "https://github.com/ansible/django-ansible-base.git"

    def test_mask_token_in_url(self):
        """Test token masking in URLs"""
        url = "https://ghp_1234567890abcdef@github.com/ansible/repo.git"
        masked = get_pr_checkout.mask_token_in_url(url)
        assert masked == "https://***@github.com/ansible/repo.git"
        assert "ghp_" not in masked


class TestExecuteGitClone:
    """Test the execute_git_clone function"""

    @patch("get_pr_checkout.subprocess.run")
    @patch("get_pr_checkout.shutil.which")
    def test_clone_with_branch_success(self, mock_which, mock_run):
        """Test successful git clone with branch"""
        mock_which.return_value = "/usr/bin/git"
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

        result = get_pr_checkout.execute_git_clone("https://token@github.com/ansible/repo.git", "feature-branch", "target-dir")

        assert result is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "git" in cmd
        assert "feature-branch" in cmd
        assert "target-dir" in cmd
        assert "--depth=1" in cmd

    @patch("get_pr_checkout.subprocess.run")
    @patch("get_pr_checkout.shutil.which")
    def test_clone_without_branch_success(self, mock_which, mock_run):
        """Test successful git clone without branch"""
        mock_which.return_value = "/usr/bin/git"
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

        result = get_pr_checkout.execute_git_clone("https://github.com/ansible/repo.git", None, "target-dir")

        assert result is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "-b" not in cmd
        assert "target-dir" in cmd

    @patch("get_pr_checkout.subprocess.run")
    @patch("get_pr_checkout.shutil.which")
    def test_clone_failure(self, mock_which, mock_run):
        """Test git clone failure"""
        mock_which.return_value = "/usr/bin/git"
        mock_run.return_value = MagicMock(returncode=128, stderr="fatal: repository not found", stdout="")

        result = get_pr_checkout.execute_git_clone("https://github.com/ansible/repo.git", "branch", "target-dir")

        assert result is False

    @patch("get_pr_checkout.shutil.which")
    def test_clone_git_not_found(self, mock_which):
        """Test when git is not available"""
        mock_which.return_value = None

        result = get_pr_checkout.execute_git_clone("https://github.com/ansible/repo.git", "branch", "target-dir")

        assert result is False


class TestBranchExists:
    """Test the branch_exists function"""

    @patch("get_pr_checkout.make_api_request")
    def test_branch_exists_true(self, mock_api):
        """Test when branch exists"""
        mock_api.return_value = {"name": "devel"}  # Return dict on success

        result = get_pr_checkout.branch_exists("ansible/repo", "devel", "token")
        assert result is True

    @patch("get_pr_checkout.make_api_request")
    def test_branch_exists_false(self, mock_api):
        """Test when branch doesn't exist"""
        mock_api.return_value = None  # Return None on failure

        result = get_pr_checkout.branch_exists("ansible/repo", "missing", "token")
        assert result is False


class TestMainScenarios:
    """Test main() function with various scenarios"""

    @patch("get_pr_checkout.execute_git_clone")
    @patch("get_pr_checkout.make_api_request")
    def test_explicit_requirement_open_pr(self, mock_api, mock_clone, monkeypatch):
        """Test explicit PR requirement (open PR)"""
        monkeypatch.setenv("PR_BODY", "Requires ansible/django-ansible-base#123")
        monkeypatch.setenv("GH_TOKEN", "test_token")
        monkeypatch.setenv("GITHUB_BASE_REF", "devel")
        _set_cli_args("ansible/django-ansible-base")

        # Mock PR API response (return dict directly)
        pr_data = {"number": 123, "merged": False, "head": {"ref": "feature-branch", "repo": {"full_name": "user/django-ansible-base"}}}
        mock_api.return_value = pr_data
        mock_clone.return_value = True

        with pytest.raises(SystemExit) as exc_info:
            get_pr_checkout.main()

        assert exc_info.value.code == 0
        mock_clone.assert_called_once()

    @patch("get_pr_checkout.execute_git_clone")
    @patch("get_pr_checkout.make_api_request")
    def test_explicit_requirement_merged_pr(self, mock_api, mock_clone, monkeypatch):
        """Test explicit PR requirement (merged PR)"""
        monkeypatch.setenv("PR_BODY", "Requires ansible/django-ansible-base#456")
        monkeypatch.setenv("GH_TOKEN", "test_token")
        monkeypatch.setenv("GITHUB_BASE_REF", "devel")
        _set_cli_args("ansible/django-ansible-base")

        # Mock PR API response (return dict directly)
        pr_data = {"number": 456, "merged": True, "base": {"ref": "devel", "repo": {"full_name": "ansible/django-ansible-base"}}}
        mock_api.return_value = pr_data
        mock_clone.return_value = True

        with pytest.raises(SystemExit) as exc_info:
            get_pr_checkout.main()

        assert exc_info.value.code == 0

    @patch("get_pr_checkout.execute_git_clone")
    @patch("get_pr_checkout.branch_exists")
    def test_branch_matching_devel(self, mock_branch_exists, mock_clone, monkeypatch):
        """Test branch matching on devel"""
        monkeypatch.setenv("PR_BODY", "No requirements")
        monkeypatch.setenv("GH_TOKEN", "test_token")
        monkeypatch.setenv("GITHUB_BASE_REF", "devel")
        _set_cli_args("ansible/django-ansible-base")

        mock_branch_exists.return_value = True
        mock_clone.return_value = True

        with pytest.raises(SystemExit) as exc_info:
            get_pr_checkout.main()

        assert exc_info.value.code == 0
        mock_clone.assert_called_once()

    @patch("get_pr_checkout.execute_git_clone")
    @patch("get_pr_checkout.branch_exists")
    def test_branch_matching_stable(self, mock_branch_exists, mock_clone, monkeypatch):
        """Test branch matching on stable branch"""
        monkeypatch.setenv("PR_BODY", "No requirements")
        monkeypatch.setenv("GH_TOKEN", "test_token")
        monkeypatch.setenv("GITHUB_BASE_REF", "devel")
        _set_cli_args("ansible/django-ansible-base")

        mock_branch_exists.return_value = True
        mock_clone.return_value = True

        with pytest.raises(SystemExit) as exc_info:
            get_pr_checkout.main()

        assert exc_info.value.code == 0
        mock_clone.assert_called_once()

    @patch("get_pr_checkout.branch_exists")
    def test_devel_fails_without_matching_branch(self, mock_branch_exists, monkeypatch):
        """Test devel fails when no matching branch exists (no fallback)"""
        monkeypatch.setenv("PR_BODY", "No requirements")
        monkeypatch.setenv("GH_TOKEN", "test_token")
        monkeypatch.setenv("GITHUB_BASE_REF", "devel")
        _set_cli_args("ansible/django-ansible-base")

        # Branch doesn't exist
        mock_branch_exists.return_value = False

        with pytest.raises(SystemExit) as exc_info:
            get_pr_checkout.main()

        # Should fail - no fallback for devel
        assert exc_info.value.code == 1

    @patch("get_pr_checkout.branch_exists")
    def test_stable_fails_without_matching_branch(self, mock_branch_exists, monkeypatch):
        """Test stable branch fails when no matching branch exists"""
        monkeypatch.setenv("PR_BODY", "No requirements")
        monkeypatch.setenv("GH_TOKEN", "test_token")
        monkeypatch.setenv("GITHUB_BASE_REF", "devel")
        _set_cli_args("ansible/django-ansible-base")

        # Branch doesn't exist
        mock_branch_exists.return_value = False

        with pytest.raises(SystemExit) as exc_info:
            get_pr_checkout.main()

        # Should fail
        assert exc_info.value.code == 1

    @patch("get_pr_checkout.execute_git_clone")
    @patch("get_pr_checkout.branch_exists")
    def test_enterprise_fallback(self, mock_branch_exists, mock_clone, monkeypatch):
        """Test enterprise repo fallback when first variant doesn't have branch"""
        monkeypatch.setenv("PR_BODY", "No requirements")
        monkeypatch.setenv("GH_TOKEN", "test_token")
        monkeypatch.setenv("GITHUB_BASE_REF", "devel")
        _set_cli_args("ansible/django-ansible-base")

        # First call (enterprise) returns False, second call (public) returns True
        mock_branch_exists.side_effect = [False, True]
        mock_clone.return_value = True

        with pytest.raises(SystemExit) as exc_info:
            get_pr_checkout.main()

        assert exc_info.value.code == 0
        assert mock_branch_exists.call_count == 2

    @patch("get_pr_checkout.execute_git_clone")
    @patch("get_pr_checkout.make_api_request")
    def test_multiple_explicit_requirements(self, mock_api, mock_clone, monkeypatch):
        """Test multiple explicit requirements"""
        pr_body = "Requires ansible/django-ansible-base#123, ansible/ansible.platform#456"
        monkeypatch.setenv("PR_BODY", pr_body)
        monkeypatch.setenv("GH_TOKEN", "test_token")
        monkeypatch.setenv("GITHUB_BASE_REF", "devel")
        _set_cli_args("ansible/django-ansible-base", "ansible/ansible.platform")

        # Mock PR API responses
        pr_data_dab = {"number": 123, "merged": False, "head": {"ref": "dab-feature", "repo": {"full_name": "user/django-ansible-base"}}}
        pr_data_collection = {"number": 456, "merged": False, "head": {"ref": "collection-feature", "repo": {"full_name": "user/ansible.platform"}}}
        mock_api.side_effect = [pr_data_dab, pr_data_collection]  # Return dicts directly
        mock_clone.return_value = True

        with pytest.raises(SystemExit) as exc_info:
            get_pr_checkout.main()

        assert exc_info.value.code == 0
        assert mock_clone.call_count == 2

    @patch("get_pr_checkout.execute_git_clone")
    @patch("get_pr_checkout.make_api_request")
    @patch("get_pr_checkout.branch_exists")
    def test_mixed_explicit_and_branch_matching(self, mock_branch_exists, mock_api, mock_clone, monkeypatch):
        """Test one explicit requirement and one branch match"""
        pr_body = "Requires ansible/django-ansible-base#123"
        monkeypatch.setenv("PR_BODY", pr_body)
        monkeypatch.setenv("GH_TOKEN", "test_token")
        monkeypatch.setenv("GITHUB_BASE_REF", "devel")
        _set_cli_args("ansible/django-ansible-base", "ansible/ansible.platform")

        # Mock PR API response for DAB (return dict directly)
        pr_data = {"number": 123, "merged": False, "head": {"ref": "feature-branch", "repo": {"full_name": "user/django-ansible-base"}}}
        mock_api.return_value = pr_data

        # Mock branch exists for collection
        mock_branch_exists.return_value = True
        mock_clone.return_value = True

        with pytest.raises(SystemExit) as exc_info:
            get_pr_checkout.main()

        assert exc_info.value.code == 0
        assert mock_clone.call_count == 2

    @patch("get_pr_checkout.execute_git_clone")
    @patch("get_pr_checkout.branch_exists")
    def test_repo_variant_single_org(self, mock_branch_exists, mock_clone, monkeypatch):
        """Test single org repo works as expected"""
        monkeypatch.setenv("PR_BODY", "No requirements")
        monkeypatch.setenv("GH_TOKEN", "test_token")
        monkeypatch.setenv("GITHUB_BASE_REF", "devel")
        _set_cli_args("ansible/django-ansible-base")

        mock_branch_exists.return_value = True
        mock_clone.return_value = True

        with pytest.raises(SystemExit) as exc_info:
            get_pr_checkout.main()

        assert exc_info.value.code == 0
        # Verify it checked the correct repo
        mock_branch_exists.assert_called_once()
        call_args = mock_branch_exists.call_args[0]
        assert "ansible/django-ansible-base" in call_args[0]

    def test_no_repos_specified(self, monkeypatch):
        """Test that script succeeds when no repos specified (clones nothing)"""
        monkeypatch.setenv("PR_BODY", "No requirements")
        monkeypatch.setenv("GH_TOKEN", "test_token")
        monkeypatch.setenv("GITHUB_BASE_REF", "devel")
        _set_cli_args()  # No repos

        with pytest.raises(SystemExit) as exc_info:
            get_pr_checkout.main()

        assert exc_info.value.code == 0

    def test_invalid_repo_format(self, monkeypatch):
        """Test that script fails with invalid repo format"""
        monkeypatch.setenv("PR_BODY", "No requirements")
        monkeypatch.setenv("GH_TOKEN", "test_token")
        sys.argv = ["get_pr_checkout.py", "--always-clone-repos", "invalid-repo-format"]

        with pytest.raises(SystemExit) as exc_info:
            get_pr_checkout.main()

        assert exc_info.value.code == 1

    @patch("get_pr_checkout.make_api_request")
    def test_explicit_requirement_api_failure(self, mock_api, monkeypatch):
        """Test that explicit requirement with API failure causes exit"""
        monkeypatch.setenv("PR_BODY", "Requires ansible/django-ansible-base#999")
        monkeypatch.setenv("GH_TOKEN", "test_token")
        monkeypatch.setenv("GITHUB_BASE_REF", "devel")
        _set_cli_args("ansible/django-ansible-base")

        # Mock API failure (return None)
        mock_api.return_value = None

        with pytest.raises(SystemExit) as exc_info:
            get_pr_checkout.main()

        assert exc_info.value.code == 1
