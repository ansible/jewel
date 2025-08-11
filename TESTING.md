# Testing Guide for Gateway

This document outlines the testing procedures and requirements for the gateway project.

## Test Runner

**Important**: Use `tox` instead of `pytest` directly for running tests in this project.

### Why tox?

The Gateway project requires specific Django configuration, database setup, and environment management that `tox` handles automatically. Running `pytest` directly will result in Django configuration errors like:

```
django.core.exceptions.ImproperlyConfigured: Requested setting USE_I18N, but settings are not configured.
```

### Running Tests

#### Run all tests:
```bash
tox -e 311
```

#### Run specific test patterns:
```bash
tox -e 311 -- -k "test_pattern_name" -v
```

#### Run tests in a specific file:
```bash
tox -e 311 -- aap_gateway_api/tests/path/to/test_file.py -v
```

#### Run a specific test function:
```bash
tox -e 311 -- -k "test_function_name" -v
```

### Examples

```bash
# Run CSRF validation tests
tox -e 311 -- -k "test_csrf" -v

# Run all preference tests
tox -e 311 -- aap_gateway_api/tests/preferences/ -v

# Run a specific test
tox -e 311 -- -k "test_csrf_trusted_origins_type" -v
```

## Test Environment

- **Python Version**: 3.11
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
tox -e 311
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
- **black**: Code formatting
- **flake8**: Linting
- **isort**: Import sorting

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

If you need to debug failing tests:
1. Use `tox -e 311 -- -v -s` for verbose output without capture
2. Add `breakpoint()` for debugging breakpoints
3. Check the test database state if needed
4. Review Django settings in `aap_gateway_api.tests.settings_overrides`

## Common Issues

### Django Configuration Errors
- **Problem**: `ImproperlyConfigured` errors about settings
- **Solution**: Always use `tox -e 311` instead of `pytest` directly

### Database Issues
- **Problem**: Database connection or migration errors
- **Solution**: tox manages the test database automatically via Docker

### Import Errors
- **Problem**: Module import failures
- **Solution**: Ensure you're running tests from the project root directory
