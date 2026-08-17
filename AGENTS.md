# AGENTS.md

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
- Use `GATEWAY_TEST_DIRS` environment variable to control which test directories are collected.
- If `django-ansible-base/` contains a checkout, refer to its own `README.md` and `test_app/README.md` for testing instructions.

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

- **Coverage Requirement**: SonarCloud requires 90%+ code coverage for quality gates
- **Service Authentication**: All services use JWT token authentication
- **Secrets Management**: Never commit secrets
- **Pre-commit Hooks**: Always run to catch security and quality issues

### GitHub Actions Security

- **NEVER use user-controlled data directly in run blocks**
  → Always pass through environment variables (e.g., `github.event.pull_request.body`)
- **Bad:** `echo "${{ github.event.pull_request.body }}" > file.txt`
- **Good:** Use env block and reference variables:
  ```yaml
  env:
    PR_BODY: ${{ github.event.pull_request.body }}
  run: |
    printf '%s' "$PR_BODY" > file.txt
  ```
- GitHub Actions sanitizes environment variables before passing to shell
- This prevents command injection vulnerabilities

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
- Use `git commit --amend` for iterative fixes
- Always give AI co-author credit in commits when applicable

## Additional Resources

For user-specific preferences and instructions, check `AGENTS_USER.md` if it exists in the repository.
