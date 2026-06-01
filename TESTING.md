# Testing Guide for Gateway

This document outlines the testing procedures and requirements for the gateway project.

## Test Runner

**Important**: Use `tox` instead of `pytest` directly for running tests in this project.

### Why tox?

The Gateway project requires specific Django configuration, database setup, and environment management that `tox` handles automatically. Running `pytest` directly will result in Django configuration errors like:

```
django.core.exceptions.ImproperlyConfigured: Requested setting USE_I18N, but settings are not configured.
```

## Parallel Testing

The Gateway test suite **supports parallel test execution** using `pytest-xdist`. Tests run in parallel by default in CI and can be run in parallel locally.

### How Parallel Testing Works

- **Automatic**: Tests run in parallel by default using `pytest-xdist`
- **Worker Isolation**: Each test worker gets its own database and cache namespace
- **Process Count**: Controlled by `PYTEST_NUM_PROCESSES` environment variable
- **Database Isolation**: Each worker uses separate test database files (`db_test.sqlite3_gw0`, `db_test.sqlite3_gw1`, etc.)

### Controlling Parallel Execution

```bash
# Run with specific number of workers
PYTEST_NUM_PROCESSES=4 tox -e py312

# Run single-threaded (for debugging)
PYTEST_NUM_PROCESSES=1 tox -e py312

# Use auto-detection (default)
PYTEST_NUM_PROCESSES=auto tox -e py312
```

### Running Tests

#### Run all tests:
```bash
tox -e py312
```

#### Run specific test patterns:
```bash
tox -e py312 -- -k "test_pattern_name" -v
```

#### Run tests in a specific file:
```bash
tox -e py312 -- aap_gateway_api/tests/path/to/test_file.py -v
```

#### Run a specific test function:
```bash
tox -e py312 -- -k "test_function_name" -v
```

### Examples

```bash
# Run CSRF validation tests
tox -e py312 -- -k "test_csrf" -v

# Run all preference tests
tox -e py312 -- aap_gateway_api/tests/preferences/ -v

# Run a specific test
tox -e py312 -- -k "test_csrf_trusted_origins_type" -v
```

## Test Environment

- **Python Version**: 3.12
- **Test Framework**: pytest (via tox)
- **Database**: PostgreSQL (managed by Docker via tox)
- **Django Settings**: Configured automatically by tox environment

## django-ansible-base Testing

The `django-ansible-base/` folder in this repository can either be:
- **Empty**: When using the installed package version
- **Checkout**: When containing a local checkout of the django-ansible-base repository

### If django-ansible-base contains a checkout:
When the `django-ansible-base/` folder contains actual code (not empty), run tests from within that directory:

```bash
cd django-ansible-base
tox -e py312
```

Or potentially:
```bash
cd django-ansible-base
pytest  # May work due to configured Django settings
```

The django-ansible-base repository has its own test configuration and can run independently of the main Gateway tests.

## Coverage

Tests include coverage reporting. Coverage reports are generated in:
- HTML: `htmlcov/`
- XML: `coverage.xml`
- JSON: `coverage.json`

**Note**: SonarCloud requires 80% code coverage for quality gates.

## Pre-commit Hooks

The project uses pre-commit hooks that run automatically on commit:
- **ruff**: Fast Python linter and formatter (replaces black, flake8, and isort)

## Test Structure

Tests are organized under `aap_gateway_api/tests/` and mimic the same directory structure as the `aap_gateway_api` module:
- `authentication/` - Authentication-related tests
- `preferences/` - Settings and preferences tests
- `utils/` - Utility function tests
- `views/` - API view tests
- And more...

## Writing Tests

When writing new tests:
1. Place them in the appropriate subdirectory under `aap_gateway_api/tests/`
2. Use descriptive test names
3. Include both positive and negative test cases
4. Test edge cases and error conditions
5. Use `@pytest.mark.parametrize` for multiple test scenarios

## Debugging Tests

### General Debugging

If you need to debug failing tests:

1. Use `tox -e py312 -- -v -s` for verbose output without capture
2. Add `breakpoint()` for debugging breakpoints
3. Check the test database state if needed
4. Review Django settings in `aap_gateway_api.tests.settings_overrides`

### Debugging Parallel Test Issues

For debugging parallel execution problems:

```bash
# Run single-threaded to isolate issues
PYTEST_NUM_PROCESSES=1 tox -e py312 -- -v -s

# Run specific failing tests in isolation
tox -e py312 -- -k "test_specific_failing_test" -v -s

# Check for race conditions by running multiple times
for i in {1..5}; do tox -e py312 -- -k "test_name" -v; done
```

## Common Issues

### Django Configuration Errors

- **Problem**: `ImproperlyConfigured` errors about settings
- **Solution**: Always use `tox -e py312` instead of `pytest` directly

### Database Issues
- **Problem**: Database connection or migration errors
- **Solution**: tox manages the test database automatically via Docker

### Import Errors
- **Problem**: Module import failures
- **Solution**: Ensure you're running tests from the project root directory

### Parallel Testing Issues

#### System User Conflicts
- **Problem**: `IntegrityError: duplicate key value violates unique constraint "aap_gateway_api_user_username_key"` with `(_system)` user
- **Solution**: Fixed in the codebase with proper race condition handling

#### Cache Conflicts
- **Problem**: Tests interfering with each other's cache state
- **Solution**: Use the `isolated_cache` fixture for cache-dependent tests

#### Settings Override Conflicts
- **Problem**: `@override_settings` affecting other parallel workers
- **Solution**: Settings are now properly isolated per worker

#### Port Conflicts
- **Problem**: Service test apps trying to use the same ports
- **Solution**: Automatically handled with worker-specific port assignment

### Performance Considerations
- **Parallel tests are faster**: Typically 3-5x faster than single-threaded
- **Memory usage**: Each worker uses additional memory for its own database
- **CPU usage**: Optimal worker count is usually number of CPU cores
- **I/O bound tests**: May benefit from more workers than CPU cores

## Test Fixtures & Patterns

### Preference Management (CRITICAL)
**NEVER use `set_preference` fixture** - it has been completely removed from the codebase.

**USE `preference_manager` fixture** for all preference tests:

```python
# Single preference
def test_something(preference_manager):
    with preference_manager.set("section", "name", value):
        # Test code here
        pass

# Multiple preferences
def test_multiple(preference_manager):
    with preference_manager.set_multiple({
        ("local_login", "password_min_upper"): 2,
        ("local_login", "password_min_special"): 2,
        ("local_login", "password_min_length"): 8,
    }):
        # Test code here
        pass
```

**Benefits:**
- Context manager provides automatic cleanup
- Proper isolation between parallel test workers
- Only tracks preferences that are actually changed
- Guarantees cleanup even if test fails

### Service Tests & JWT Authentication
All service fixtures depend on `ensure_jwt_keys` for authentication:

**Service Fixtures:**
- `simulated_controller_resource_api`
- `simmulated_hub_resource_api`
- `simulated_eda_resource_api`
- `migration_service*` (all variants)

**How it works:**
- JWT keys are auto-generated per test worker for parallel execution safety
- Each worker gets unique JWT keypair to prevent authentication conflicts
- Service fixtures automatically depend on `ensure_jwt_keys` fixture

**Common Issue:**
```
403 Client Error: Forbidden
Response content: {"detail":"Authentication credentials were not provided."}
```
**Solution:** Ensure service fixture has `ensure_jwt_keys` dependency:
```python
@pytest.fixture
def my_service_fixture(patched_resource_client, service_route, ensure_jwt_keys):
    # Service setup code
```

### Cache Isolation
Uses `WorkerIsolatedRedisCache` backend for parallel test safety:

```python
def test_cache_dependent(isolated_cache):
    isolated_cache.set('key', 'value')
    # Test code
    # Cache automatically cleaned up
```

**How it works:**
- Each pytest-xdist worker gets isolated cache prefix (`worker_gw0_`, `worker_gw1_`, etc.)
- `cache.clear()` only clears current worker's keys
- Prevents parallel test workers from interfering with each other

## CI Structure

### 3-Batch Parallel Strategy
Tests are split into 3 parallel batches in CI:

1. **Service-dependent tests**: Single-threaded, includes migration and service tests
2. **Views directory**: 2 threads, all tests under `aap_gateway_api/tests/views/`
3. **Remaining tests**: 2 threads, everything else

Each batch produces separate coverage/JUnit files, final job merges using `junitparser`.

### Stress Testing
Use `./run_tox_batch.sh` to run tox 40 times for detecting intermittent threading issues:

```bash
chmod +x run_tox_batch.sh
./run_tox_batch.sh
```

## Common Threading Issues & Solutions

### Service Authentication Failures
**Symptom:** Intermittent failures with "Authentication credentials were not provided"
**Cause:** Service fixture missing `ensure_jwt_keys` dependency
**Solution:** Add `ensure_jwt_keys` parameter to service fixture

### Cache Pollution Between Tests
**Symptom:** Tests pass individually but fail when run together
**Cause:** Tests not properly cleaning up cache state
**Solution:** Use `isolated_cache` fixture instead of direct cache access

### Preference Interference
**Symptom:** Preference-dependent tests failing intermittently
**Cause:** Using deprecated `set_preference` or manual preference management
**Solution:** Migrate to `preference_manager` fixture with context managers

### Import Errors for Missing Modules
**Symptom:** `ModuleNotFoundError` during test collection
**Cause:** Stray test files importing non-existent utility modules
**Solution:** Remove orphaned test files or create missing modules

### Debugging Threading Issues
1. **Isolate the problem:** Run single-threaded first
2. **Stress test:** Use batch runner to reproduce intermittent failures
3. **Check fixtures:** Ensure proper dependencies and cleanup
4. **Verify isolation:** Each worker should be completely independent

<!-- test: label workflow validation -->
