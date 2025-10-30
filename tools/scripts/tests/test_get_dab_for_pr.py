#!/usr/bin/env python3
"""
Integration tests for get_dab_for_pr.py

Run with:
    pytest tools/scripts/tests/test_get_dab_for_pr.py -v --cov=tools/scripts/get_dab_for_pr --cov-report=term-missing

For manual testing with real tokens:
    export GH_TOKEN="your_github_token"
    export ANSIBLE_TOKEN="your_token"  # optional
    pytest tools/scripts/tests/test_get_dab_for_pr.py -v -k manual
"""

import os
import sys
from typing import Any, Dict, Optional
from unittest.mock import patch

import pytest

# Add parent directory to path so we can import the script
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import get_dab_for_pr  # noqa: E402


class MockResponse:
    """Mock requests.Response object"""

    def __init__(self, status_code: int, json_data: Optional[Dict[str, Any]] = None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self):
        return self._json_data


class TestMakeGithubApiRequest:
    """Test the make_github_api_request function"""

    @patch("get_dab_for_pr.requests.get")
    def test_public_repo_with_gh_token(self, mock_get):
        """Test API request to public repo with GH_TOKEN"""
        mock_get.return_value = MockResponse(200, {"test": "data"})

        url = "https://api.github.com/repos/ansible/django-ansible-base/branches/devel"
        response = get_dab_for_pr.make_github_api_request(url, "test_gh_token", None)

        assert response.status_code == 200
        mock_get.assert_called_once()
        call_headers = mock_get.call_args[1]["headers"]
        assert call_headers["Authorization"] == "Bearer test_gh_token"

    @patch("get_dab_for_pr.requests.get")
    def test_enterprise_repo_with_aap_token(self, mock_get):
        """Test API request to enterprise repo with ANSIBLE_TOKEN"""
        mock_get.return_value = MockResponse(200, {"test": "data"})

        url = "https://api.github.com/repos/ansible/django-ansible-base/branches/stable-2.5"
        response = get_dab_for_pr.make_github_api_request(url, "test_gh_token", "test_aap_token")

        assert response.status_code == 200
        mock_get.assert_called_once()
        call_headers = mock_get.call_args[1]["headers"]
        assert call_headers["Authorization"] == "Bearer test_aap_token"

    @patch("get_dab_for_pr.requests.get")
    def test_enterprise_repo_with_gh_token_only(self, mock_get):
        """Test API request to enterprise repo with GH_TOKEN when ANSIBLE_TOKEN not set"""
        mock_get.return_value = MockResponse(200, {"test": "data"})

        url = "https://api.github.com/repos/ansible/django-ansible-base/branches/stable-2.5"
        response = get_dab_for_pr.make_github_api_request(url, "test_gh_token", None)

        assert response.status_code == 200
        mock_get.assert_called_once()
        call_headers = mock_get.call_args[1]["headers"]
        assert call_headers["Authorization"] == "Bearer test_gh_token"

    @patch("get_dab_for_pr.requests.get")
    def test_no_auth_public_repo(self, mock_get):
        """Test API request to public repo with no tokens"""
        mock_get.return_value = MockResponse(200, {"test": "data"})

        url = "https://api.github.com/repos/ansible/django-ansible-base/branches/devel"
        response = get_dab_for_pr.make_github_api_request(url, None, None)

        assert response.status_code == 200
        mock_get.assert_called_once()
        call_headers = mock_get.call_args[1]["headers"]
        assert call_headers == {}

    @patch("get_dab_for_pr.requests.get")
    def test_auth_failure_exits(self, mock_get):
        """Test that 401/403 responses cause sys.exit"""
        mock_get.return_value = MockResponse(401)

        url = "https://api.github.com/repos/ansible/django-ansible-base/branches/devel"

        with pytest.raises(SystemExit) as exc_info:
            get_dab_for_pr.make_github_api_request(url, "test_gh_token", None)

        assert exc_info.value.code == 1


class TestEndToEndScenarios:
    """End-to-end test scenarios for the entire script"""

    @patch("get_dab_for_pr.os.system")
    @patch("get_dab_for_pr.requests.get")
    def test_requires_unmerged_pr_public_repo(self, mock_get, mock_system):
        """Test: requires link to unmerged PR in public repo"""
        mock_system.return_value = 0  # git clone success

        # Mock PR API response - unmerged PR
        pr_response = MockResponse(
            200,
            {
                "merged": False,
                "head": {
                    "ref": "feature-branch",
                    "repo": {"full_name": "ansible/django-ansible-base"},
                },
            },
        )
        mock_get.return_value = pr_response

        with patch.dict(
            os.environ,
            {
                "PR_BODY": "requires ansible/django-ansible-base#123",
                "GH_TOKEN": "test_token",
                "ANSIBLE_TOKEN": "",
                "GITHUB_BASE_REF": "",
                "GITHUB_REF_NAME": "",
            },
            clear=True,
        ):
            with pytest.raises(SystemExit) as exc_info:
                get_dab_for_pr.main()

            assert exc_info.value.code == 0
            mock_system.assert_called_once()
            clone_cmd = mock_system.call_args[0][0]
            assert "git clone" in clone_cmd
            assert "feature-branch" in clone_cmd
            assert "ansible/django-ansible-base" in clone_cmd

    @patch("get_dab_for_pr.os.system")
    @patch("get_dab_for_pr.requests.get")
    def test_requires_merged_pr_uses_base_branch(self, mock_get, mock_system):
        """Test: requires link to merged PR clones base branch"""
        mock_system.return_value = 0

        # Mock PR API response - merged PR
        pr_response = MockResponse(
            200,
            {
                "merged": True,
                "base": {
                    "ref": "stable-2.5",
                    "repo": {"full_name": "ansible/django-ansible-base"},
                },
            },
        )
        mock_get.return_value = pr_response

        with patch.dict(
            os.environ,
            {
                "PR_BODY": "requires ansible/django-ansible-base#456",
                "GH_TOKEN": "test_token",
                "ANSIBLE_TOKEN": "test_aap_token",
                "GITHUB_BASE_REF": "",
                "GITHUB_REF_NAME": "",
            },
            clear=True,
        ):

            with pytest.raises(SystemExit) as exc_info:
                get_dab_for_pr.main()

            assert exc_info.value.code == 0
            mock_system.assert_called_once()
            clone_cmd = mock_system.call_args[0][0]
            assert "stable-2.5" in clone_cmd

    @patch("get_dab_for_pr.os.system")
    @patch("get_dab_for_pr.requests.get")
    def test_no_requires_finds_matching_branch_public(self, mock_get, mock_system):
        """Test: No requires, finds matching branch in public repo"""
        mock_system.return_value = 0

        # Mock branch check - found in public repo
        mock_get.return_value = MockResponse(200, {"name": "devel"})

        with patch.dict(
            os.environ,
            {
                "PR_BODY": "Some PR description without requires",
                "GH_TOKEN": "test_token",
                "ANSIBLE_TOKEN": "",
                "GITHUB_BASE_REF": "devel",
                "GITHUB_REF_NAME": "",
            },
            clear=True,
        ):

            with pytest.raises(SystemExit) as exc_info:
                get_dab_for_pr.main()

            assert exc_info.value.code == 0
            mock_system.assert_called_once()
            clone_cmd = mock_system.call_args[0][0]
            assert "devel" in clone_cmd
            assert "ansible/django-ansible-base" in clone_cmd

    @patch("get_dab_for_pr.os.system")
    @patch("get_dab_for_pr.requests.get")
    def test_no_requires_404_public_then_found_enterprise(self, mock_get, mock_system):
        """Test: No requires, 404 in public repo, found in enterprise"""
        mock_system.return_value = 0

        # Mock branch checks - 404 in public, 200 in enterprise
        def side_effect(*args, **kwargs):
            url = args[0]
            if "ansible/django-ansible-base" in url:
                return MockResponse(404)
            else:  # enterprise repo
                return MockResponse(200, {"name": "stable-2.5"})

        mock_get.side_effect = side_effect

        with patch.dict(
            os.environ,
            {
                "PR_BODY": "No requires here",
                "GH_TOKEN": "test_token",
                "ANSIBLE_TOKEN": "test_aap_token",
                "GITHUB_BASE_REF": "stable-2.5",
                "GITHUB_REF_NAME": "",
            },
            clear=True,
        ):

            with pytest.raises(SystemExit) as exc_info:
                get_dab_for_pr.main()

            assert exc_info.value.code == 0
            mock_system.assert_called_once()
            clone_cmd = mock_system.call_args[0][0]
            assert "stable-2.5" in clone_cmd
            assert "ansible/django-ansible-base" in clone_cmd

    @patch("get_dab_for_pr.requests.get")
    def test_no_requires_branch_not_found_exits(self, mock_get):
        """Test: No requires, branch not found anywhere - should exit with error"""
        # Mock branch checks - 404 everywhere
        mock_get.return_value = MockResponse(404)

        with patch.dict(
            os.environ,
            {
                "PR_BODY": "No requires",
                "GH_TOKEN": "test_token",
                "ANSIBLE_TOKEN": "test_aap_token",
                "GITHUB_BASE_REF": "nonexistent-branch",
                "GITHUB_REF_NAME": "",
            },
            clear=True,
        ):

            with pytest.raises(SystemExit) as exc_info:
                get_dab_for_pr.main()

            assert exc_info.value.code == 1

    @patch("get_dab_for_pr.requests.get")
    def test_requires_pr_not_found_exits(self, mock_get):
        """Test: requires PR that doesn't exist - should exit with error"""
        # Mock PR API - 404
        mock_get.return_value = MockResponse(404)

        with patch.dict(
            os.environ,
            {
                "PR_BODY": "requires ansible/django-ansible-base#99999",
                "GH_TOKEN": "test_token",
                "ANSIBLE_TOKEN": "",
                "GITHUB_BASE_REF": "",
                "GITHUB_REF_NAME": "",
            },
            clear=True,
        ):

            with pytest.raises(SystemExit) as exc_info:
                get_dab_for_pr.main()

            assert exc_info.value.code == 1

    @patch("get_dab_for_pr.os.system")
    @patch("get_dab_for_pr.requests.get")
    def test_git_clone_failure_exits_with_code(self, mock_get, mock_system):
        """Test: git clone fails - should exit with git's exit code"""
        mock_system.return_value = 128  # Git error code

        mock_get.return_value = MockResponse(200, {"name": "devel"})

        with patch.dict(
            os.environ,
            {
                "PR_BODY": "No requires",
                "GH_TOKEN": "test_token",
                "ANSIBLE_TOKEN": "",
                "GITHUB_BASE_REF": "devel",
                "GITHUB_REF_NAME": "",
            },
            clear=True,
        ):

            with pytest.raises(SystemExit) as exc_info:
                get_dab_for_pr.main()

            assert exc_info.value.code == 128

    @patch("get_dab_for_pr.requests.get")
    def test_branch_check_500_error_exits(self, mock_get):
        """Test: 500 error when checking branch - should exit"""
        # Mock API error
        mock_get.return_value = MockResponse(500)

        with patch.dict(
            os.environ,
            {
                "PR_BODY": "No requires",
                "GH_TOKEN": "test_token",
                "ANSIBLE_TOKEN": "",
                "GITHUB_BASE_REF": "devel",
                "GITHUB_REF_NAME": "",
            },
            clear=True,
        ):

            with pytest.raises(SystemExit) as exc_info:
                get_dab_for_pr.main()

            assert exc_info.value.code == 1

    @patch("get_dab_for_pr.os.system")
    @patch("get_dab_for_pr.requests.get")
    def test_no_tokens_uses_unauthenticated_clone(self, mock_get, mock_system):
        """Test: Clone without any tokens (unauthenticated)"""
        mock_system.return_value = 0
        mock_get.return_value = MockResponse(200, {"name": "devel"})

        with patch.dict(
            os.environ,
            {
                "PR_BODY": "No requires",
                "GH_TOKEN": "",
                "ANSIBLE_TOKEN": "",
                "GITHUB_BASE_REF": "devel",
                "GITHUB_REF_NAME": "",
            },
            clear=True,
        ):
            with pytest.raises(SystemExit) as exc_info:
                get_dab_for_pr.main()

            assert exc_info.value.code == 0
            mock_system.assert_called_once()
            clone_cmd = mock_system.call_args[0][0]
            # Should use plain https:// without authentication
            assert "git clone https://github.com/ansible/django-ansible-base.git" in clone_cmd


class TestSecurityAndEdgeCases:
    """Test security features and edge cases"""

    @patch("get_dab_for_pr.os.system")
    @patch("get_dab_for_pr.requests.get")
    def test_token_masking_in_output(self, mock_get, mock_system, capsys):
        """Test that tokens are masked in output"""
        mock_system.return_value = 0
        mock_get.return_value = MockResponse(200, {"name": "devel"})

        with patch.dict(
            os.environ,
            {
                "PR_BODY": "No requires",
                "GH_TOKEN": "supersecrettoken123",
                "ANSIBLE_TOKEN": "",
                "GITHUB_BASE_REF": "devel",
                "GITHUB_REF_NAME": "",
            },
            clear=True,
        ):

            with pytest.raises(SystemExit):
                get_dab_for_pr.main()

            captured = capsys.readouterr()
            # Token should be masked in output
            assert "supersecrettoken123" not in captured.out
            assert "***" in captured.out or "//***@" in captured.out

    @patch("get_dab_for_pr.os.system")
    @patch("get_dab_for_pr.requests.get")
    def test_case_insensitive_requires_match(self, mock_get, mock_system):
        """Test that requires matching is case-insensitive"""
        mock_system.return_value = 0

        pr_response = MockResponse(
            200,
            {
                "merged": False,
                "head": {
                    "ref": "feature",
                    "repo": {"full_name": "ansible/django-ansible-base"},
                },
            },
        )
        mock_get.return_value = pr_response

        with patch.dict(
            os.environ,
            {
                "PR_BODY": "REQUIRES ANSIBLE/DJANGO-ANSIBLE-BASE#123",
                "GH_TOKEN": "test_token",
                "ANSIBLE_TOKEN": "",
                "GITHUB_BASE_REF": "",
                "GITHUB_REF_NAME": "",
            },
            clear=True,
        ):

            with pytest.raises(SystemExit) as exc_info:
                get_dab_for_pr.main()

            assert exc_info.value.code == 0


@pytest.mark.manual
class TestManualIntegration:
    """
    Manual integration tests with real GitHub API
    Requires actual tokens in environment variables
    Run with: pytest -v -k manual
    """

    def test_real_github_api_public_repo(self):
        """Test with real GitHub API - public repo"""
        if not os.environ.get("GH_TOKEN"):
            pytest.skip("GH_TOKEN not set - skipping manual test")

        with patch.dict(
            os.environ,
            {
                "PR_BODY": "",
                "GITHUB_BASE_REF": "devel",
                "GITHUB_REF_NAME": "",
            },
            clear=False,
        ):

            url = "https://api.github.com/repos/ansible/django-ansible-base/branches/devel"
            response = get_dab_for_pr.make_github_api_request(url)

            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "devel"
