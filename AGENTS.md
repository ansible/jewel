# AGENTS.md

## Public Repository

This is a **public** open-source repository. Never commit, quote, or allude to internal, proprietary, customer, or non-public information in code, comments, commit messages, or pull requests. If in doubt, omit it.

## Getting Started - Required Reading

**Before proceeding with any work, please read these files in order:**

1. **README.md** - Project overview and setup instructions
2. **CONTRIBUTING.md** - Development workflow, code quality, and contribution guidelines
3. **TESTING.md** - Testing guidelines and procedures
4. **docs/** - Architecture and feature documentation (authentication, proxy, profiling, dispatcher)
5. **AGENTS_USER.md** - User-specific preferences (if it exists)
6. **django-ansible-base/README.md** - Information about the shared library (if it exists)

## Project Overview

Jewel is an open source project for an API gateway for other open source Ansible tools. Jewel is intended as the single entry point for all Ansible services, handling authentication, authorization, and proxying.

**Key Technologies:**
- Django REST Framework
- Envoy proxy
- Redis cache
- PostgreSQL database
- pytest for testing

**Related Repositories:**
- This repo may have a checkout of `django-ansible-base` in the `django-ansible-base/` directory - it's a separate git repo with its own tests and configuration
- `django-ansible-base` is a shared library providing functionality common across open source Ansible services

## Build and Test Commands

See `TESTING.md` for complete setup, test execution, and debugging instructions.

Key points for AI agents:
- **CRITICAL:** Always use `tox` instead of `pytest` directly. Direct pytest will fail with Django configuration errors.
- **CRITICAL:** When running a subset of tests, set `GATEWAY_TEST_DIRS=""` so tox does not also collect the default `aap_gateway_api/tests` directory.

```bash
# All tests
tox -e py312

# Specific tests (GATEWAY_TEST_DIRS="" prevents double collection)
GATEWAY_TEST_DIRS="" tox -e py312 -- -k "test_pattern_name" -v
GATEWAY_TEST_DIRS="" tox -e py312 -- aap_gateway_api/tests/path/to/test_file.py -v

# Single-threaded (debugging)
PYTEST_NUM_PROCESSES=1 tox -e py312
```

- If `django-ansible-base/` contains a checkout, refer to its own `README.md` and `test_app/README.md` for testing instructions.

This repository's CI covers unit and integration tests. Functional and end-to-end testing of Jewel as a product is performed in a separate test suite outside this repository.

**Coverage:** Codecov requires 90% patch coverage on new code. SonarCloud quality gates also enforce coverage.

## Code Style Guidelines

**Pre-commit Hooks** (enforced automatically):
- **ruff**: Fast Python linter and formatter (handles formatting, linting, and import sorting)

**Testing Conventions:**
- Always use parameterized tests (`@pytest.mark.parametrize`) when writing multiple similar test cases
- Place tests in appropriate subdirectory under `aap_gateway_api/tests/`
- Use descriptive test names that explain what is being tested
- Include both positive and negative test cases
- Consider whether changes warrant a performance test (see `TESTING.md` § Performance Tests)
- Please read the `TESTING.md` file for more details about testing

## Security Considerations

- **Service Authentication**: All services use JWT token authentication
- **Secrets Management**: Never commit secrets
- **Public content**: Treat every commit, comment, and PR as public. Do not include internal URLs, credentials, customer data, or non-public process details.
- **Pre-commit Hooks**: Always run to catch security and quality issues

### GitHub Actions Security

GitHub Actions does **not** sanitize environment variables or workflow expressions for shell use. Expressions (`${{ ... }}`) are interpolated as raw strings into the workflow YAML.

- **NEVER interpolate untrusted data directly into `run:` scripts** (PR title, body, branch name, commit message, issue text, etc.)
- Pass untrusted values through an intermediate environment variable, then reference that variable in the shell
- **Always quote** every shell expansion (`"$VAR"`). Unquoted expansions are subject to word-splitting and globbing
- **Never** pass untrusted values to `eval`, `bash -c`, or any generated shell code

**Bad:** `echo "${{ github.event.pull_request.body }}" > file.txt`

**Good:** Use an env block and a quoted expansion:

```yaml
env:
  PR_BODY: ${{ github.event.pull_request.body }}
run: |
  printf '%s' "$PR_BODY" > file.txt
```

The env var keeps the value out of script generation; the quoted `"$PR_BODY"` expansion is still required. Quoting is not a substitute for the env-var pattern, and the env-var pattern is not sanitization.

Fork PRs do not receive organization secrets (GitHub sets missing secrets to `""`, not `null`). Test secret fallbacks from a real fork PR, not an upstream branch.

## Architecture & Patterns

### Parallel Test Execution

- Tests run with pytest-xdist across multiple workers by default
- All fixtures designed for worker isolation (cache, preferences, JWT keys)
- Port allocation uses worker-specific offsets to prevent conflicts
- Database isolation via separate test DB files per worker

### Key Components

- **WorkerIsolatedRedisCache**: Custom cache backend for parallel test safety
- **preference_manager fixture**: Context manager for preference isolation
- **run_tests.sh**: Wrapper script that generates a per-tox-run JWT keypair, passes it to pytest via `--jwt-keypair-file`, and cleans up on exit
- **_patch_jwt_keygen**: Session-scoped autouse fixture that patches `post_migrate` to always use the tox-provided keypair
- **Service fixtures**: Auto-depend on JWT keys for authentication

### Common Gotchas

- Running a subset of tests without `GATEWAY_TEST_DIRS=""` also collects the default test directory
- Service tests failing with "Authentication credentials were not provided"
  → Missing `ensure_jwt_keys` dependency on service fixture
- Intermittent test failures → Usually cache/preference isolation issues
- Import errors for missing modules → Check for stray test files

### Debugging Methodology

- Always investigate root causes of threading/parallel test issues
- Stress test fixes with batch runs (`tools/scripts/run_tox_batch.sh`)
- Prefer systematic debugging over quick hacks
- Use single-threaded runs to isolate threading problems

## Pull Request Guidelines

- **ALWAYS check for the PR template** at `.github/PULL_REQUEST_TEMPLATE.md` and follow its structure
- Use descriptive PR titles that clearly communicate the change
- If the scope of a PR changes be sure to update the title and description of the PR
- Squash related commits into logical units
- On a shared PR, add a new commit rather than amending published history
- Always give AI co-author credit in commits when applicable
- Sanitize PR titles, descriptions, and comments: this repository is public

## Additional Resources

For user-specific preferences and instructions, check `AGENTS_USER.md` if it exists in the repository.
