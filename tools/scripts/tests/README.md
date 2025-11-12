# Testing `get_pr_checkout.py`

This directory contains comprehensive integration tests for the `get_pr_checkout.py` unified PR checkout script.

## Running Tests

### Basic Test Run

```bash
# From the repository root
pytest tools/scripts/tests/test_get_pr_checkout.py -v
```

### With Coverage Report

```bash
# Get coverage report with missing lines
pytest tools/scripts/tests/test_get_pr_checkout.py -v \
    --cov=tools/scripts/get_pr_checkout \
    --cov-report=term-missing \
    --cov-report=html

# View HTML coverage report
open htmlcov/index.html
```

### Run Specific Test Classes

```bash
# Test API request function
pytest tools/scripts/tests/test_get_pr_checkout.py::TestMakeApiRequest -v

# Test helper functions
pytest tools/scripts/tests/test_get_pr_checkout.py::TestHelperFunctions -v

# Test main scenarios
pytest tools/scripts/tests/test_get_pr_checkout.py::TestMainScenarios -v

# Test git clone execution
pytest tools/scripts/tests/test_get_pr_checkout.py::TestExecuteGitClone -v
```

### Manual Integration Tests (with real GitHub API)

These tests require actual GitHub tokens and are marked with `@pytest.mark.manual`.

```bash
# Set up tokens
export GH_TOKEN="your_github_personal_access_token"
export AAP_TOKEN="your_aap_token"  # Optional, for enterprise repo access

# Run manual tests only
pytest tools/scripts/tests/test_get_pr_checkout.py -v -k manual
```

**Note:** Manual tests will skip automatically if `GH_TOKEN` is not set.

## Test Coverage

The test suite covers:

- ✅ **GitHub PR Reference Parsing** (`parse_all_github_pr_references`)
  - Single shorthand format (org/repo#123)
  - Single URL format (https://github.com/org/repo/pull/456)
  - Multiple formats on same line with various separators
  - Multiple requires lines
  - Case-insensitive matching
  - Enterprise repo references
  - Duplicate repo handling

- ✅ **API Request Function** (`make_api_request`)
  - Requests with token authentication
  - Requests without token (public repos)

- ✅ **Helper Functions**
  - `get_current_branch` (from GITHUB_BASE_REF and GITHUB_REF_NAME)
  - `get_token` (GH_TOKEN with AAP_TOKEN fallback)
  - `extract_branch_from_pr` (open and merged PRs)
  - `build_clone_url` (with and without tokens)
  - `mask_token_in_url` (token masking in output)
  - `get_repo_variants` (public and enterprise variants)
  - `branch_exists` (branch existence checking)

- ✅ **Main Execution Scenarios**
  - Explicit `requires` link to open PR
  - Explicit `requires` link to merged PR (clones base branch)
  - Branch matching on devel
  - Branch matching on stable branches
  - Devel fallback to default branch (when no match)
  - Stable branch MUST fail without matching branch (product consistency)
  - Enterprise repo fallback (when public doesn't have branch)
  - Multiple explicit requirements
  - Mixed explicit requirements and branch matching
  - Validation (no repos specified, invalid repo format)
  - Explicit `requires` with API failure (hard exit)

- ✅ **Git Clone Execution**
  - Clone with specific branch
  - Clone without branch (default)
  - Clone failure handling
  - Git not found handling

## Expected Coverage

The test suite achieves **~100% code coverage** of `get_pr_checkout.py`.

## Test Structure

```
tools/scripts/tests/
├── __init__.py
├── README.md                   # This file
├── conftest.py                 # Pytest configuration
├── pytest.ini                  # Pytest settings
└── test_get_pr_checkout.py     # Test suite
```

## Troubleshooting

### Import Errors

If you get import errors, ensure you're running pytest from the repository root:

```bash
cd /path/to/aap-gateway
pytest tools/scripts/tests/test_get_pr_checkout.py
```

### Coverage Not 100%

If coverage is not 100%, check:
1. All code paths are tested (if/else branches)
2. Error cases are tested (sys.exit scenarios)
3. All CLI argument combinations are tested

### Manual Tests Skipped

Manual tests require `GH_TOKEN` environment variable. Set it:

```bash
export GH_TOKEN="ghp_your_token_here"
pytest tools/scripts/tests/test_get_pr_checkout.py -v -k manual
```

## CI/CD Integration

To integrate into CI/CD pipelines:

```yaml
- name: Test get_pr_checkout.py
  run: |
    pytest tools/scripts/tests/test_get_pr_checkout.py -v \
      --cov=tools/scripts/get_pr_checkout \
      --cov-report=xml \
      --cov-report=term
```

## Contributing

When modifying `get_pr_checkout.py`:
1. Run the test suite
2. Ensure ~100% coverage is maintained
3. Add tests for new functionality
4. Update this README if test commands change

