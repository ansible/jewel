# AAP Gateway Repo

Start by reviewing README.md and then TESTING.md

# Django Ansible Base

This repo may have a checkout of another project called django-ansible-base if so this is a separate git repo.

# Testing

Whenever writing a new unit test always try to make multiple tests a single parameterized test.

# Commits

Always use professional commit messages and always give yourself credit as the co-author

# Architecture & Patterns

## Parallel Test Execution
- Tests run with pytest-xdist across multiple workers by default
- All fixtures designed for worker isolation (cache, preferences, JWT keys)
- Port allocation uses worker-specific offsets to prevent conflicts
- Database isolation via separate test DB files per worker

## Key Components
- **WorkerIsolatedRedisCache**: Custom cache backend for parallel test safety
- **preference_manager fixture**: Context manager for preference isolation
- **ensure_jwt_keys fixture**: JWT authentication for service tests
- **Service fixtures**: Auto-depend on JWT keys for authentication

## Git Workflow Patterns
- Squash related commits into logical units
- Use `git commit --amend` for iterative fixes
- Professional commit messages despite colorful conversation
- Always give Claude co-author credit in commits

## Common Gotchas
- Service tests failing with "Authentication credentials were not provided"
  → Missing `ensure_jwt_keys` dependency on service fixture
- Intermittent test failures → Usually cache/preference isolation issues
- Import errors for missing modules → Check for stray test files

## Debugging Methodology
- Always investigate root causes of threading/parallel test issues
- Stress test fixes with batch runs (`./run_tox_batch.sh`)
- Prefer systematic debugging over quick hacks
- Use single-threaded runs to isolate threading problems

# User Preferences

Check the existence of a CLAUDE_USER.md file, if found review that as well for preferences specific to the user.
