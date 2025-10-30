# Testing `get_dab_for_pr.py`

This directory contains comprehensive integration tests for the `get_dab_for_pr.py` script.

## Running Tests

### Basic Test Run

```bash
# From the repository root
pytest tools/scripts/tests/test_get_dab_for_pr.py -v
```

### With Coverage Report

```bash
# Get coverage report with missing lines
pytest tools/scripts/tests/test_get_dab_for_pr.py -v \
    --cov=tools/scripts/get_dab_for_pr \
    --cov-report=term-missing \
    --cov-report=html

# View HTML coverage report
open htmlcov/index.html
```

### Run Specific Test Classes

```bash
# Test only the API request function
pytest tools/scripts/tests/test_get_dab_for_pr.py::TestMakeGithubApiRequest -v

# Test end-to-end scenarios
pytest tools/scripts/tests/test_get_dab_for_pr.py::TestEndToEndScenarios -v

# Test security features
pytest tools/scripts/tests/test_get_dab_for_pr.py::TestSecurityAndEdgeCases -v
```

### Manual Integration Tests (with real GitHub API)

These tests require actual GitHub tokens and are marked with `@pytest.mark.manual`.

```bash
# Set up tokens
export GH_TOKEN="your_github_personal_access_token"
export ANSIBLE_TOKEN="your_token"  # Optional, will fallback to GH_TOKEN

# Run manual tests only
pytest tools/scripts/tests/test_get_dab_for_pr.py -v -k manual
```

**Note:** Manual tests will skip automatically if `GH_TOKEN` is not set.

## Test Coverage

The test suite covers:

- ✅ **API Request Function** (`make_github_api_request`)
  - Public repo with GH_TOKEN
  - Enterprise repo with ANSIBLE_TOKEN
  - Enterprise repo with only GH_TOKEN (fallback)
  - No authentication (public repos)
  - Authentication failures (401/403)

- ✅ **End-to-End Scenarios**
  - `requires` link to unmerged PR (public repo)
  - `requires` link to unmerged PR (enterprise repo)
  - `requires` link to merged PR (clones base branch)
  - No `requires`, finds matching branch in public repo
  - No `requires`, 404 in public, found in enterprise
  - No `requires`, branch not found anywhere (error)
  - `requires` PR that doesn't exist (error)
  - Git clone failure (bubbles up exit code)
  - 500 error when checking branch (error)

- ✅ **Security & Edge Cases**
  - Token masking in output
  - Case-insensitive `requires` matching
  - Proper exit codes

## Expected Coverage

The test suite achieves **100% code coverage** of `get_dab_for_pr.py`.

## Test Structure

```
tools/scripts/tests/
├── __init__.py
├── README.md                   # This file
└── test_get_dab_for_pr.py     # Test suite
```

## Troubleshooting

### Import Errors

If you get import errors, ensure you're running pytest from the repository root:

```bash
cd /path/to/aap-gateway
pytest tools/scripts/tests/test_get_dab_for_pr.py
```

### Coverage Not 100%

If coverage is not 100%, check:
1. All code paths are tested (if/else branches)
2. Error cases are tested (sys.exit scenarios)
3. The script's top-level execution code is tested (via `exec()`)

### Manual Tests Skipped

Manual tests require `GH_TOKEN` environment variable. Set it:

```bash
export GH_TOKEN="ghp_your_token_here"
pytest tools/scripts/tests/test_get_dab_for_pr.py -v -k manual
```

## CI/CD Integration

To integrate into CI/CD pipelines:

```yaml
- name: Test get_dab_for_pr.py
  run: |
    pytest tools/scripts/tests/test_get_dab_for_pr.py -v \
      --cov=tools/scripts/get_dab_for_pr \
      --cov-report=xml \
      --cov-report=term
```

## Contributing

When modifying `get_dab_for_pr.py`:
1. Run the test suite
2. Ensure 100% coverage is maintained
3. Add tests for new functionality
4. Update this README if test commands change

