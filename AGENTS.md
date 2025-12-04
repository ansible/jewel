# AGENTS.md

## Getting Started - Required Reading

**Before proceeding with any work, please read these files in order:**

1. **README.md** - Project overview and setup instructions
2. **TESTING.md** - Testing guidelines and procedures
3. **AGENTS_USER.md** - User-specific preferences (if it exists)
4. **django-ansible-base/README.md** - Information about the shared library (if it exists)

## Project Overview

AAP Services Gateway provides a single entry point that sits in front of all services within Ansible Automation Platform (AAP). The gateway handles authentication, authorization, and proxying for Controller, Hub, EDA, and Lightspeed services.

**Key Technologies:**
- Django REST Framework
- Envoy proxy
- Redis cache
- PostgreSQL database
- pytest for testing

**Related Repositories:**
- This repo may have a checkout of `django-ansible-base` as a git submodule - it's a separate git repo with its own tests and configuration
- `django-ansible-base` is a library used by this project to provide additional functionality which is common across all of ansible-automation-platform

## Build and Test Commands

### Initial Setup
```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install development dependencies
pip install -r requirements/requirements_dev.txt

# Generate proxy configuration (optional)
make tools/generated/proxy.yml

# Start development environment
docker login quay.io
make docker-compose
```

### Running Tests
**CRITICAL:** Always use `tox` instead of `pytest` directly. Direct pytest will fail with Django configuration errors.

```bash
# Run all tests (parallel by default)
tox -e 311

# Run single-threaded (for debugging)
PYTEST_NUM_PROCESSES=1 tox -e 311

# Run specific tests
tox -e 311 -- -k "test_pattern_name" -v
tox -e 311 -- aap_gateway_api/tests/path/to/test_file.py -v

# Stress test for threading issues
./run_tox_batch.sh
```

### django-ansible-base Tests
```bash
cd django-ansible-base
tox -e 311
```

## Code Style Guidelines

**Pre-commit Hooks** (enforced automatically):
- **black**: Code formatting
- **flake8**: Linting  
- **isort**: Import sorting

**Testing Conventions:**
- Always use parameterized tests (`@pytest.mark.parametrize`) when writing multiple similar test cases
- Place tests in appropriate subdirectory under `aap_gateway_api/tests/`
- Use descriptive test names that explain what is being tested
- Include both positive and negative test cases
- Please read the `TESTING.md` file for more details about testing

## Security Considerations

- **Coverage Requirement**: SonarCloud requires 80% code coverage for quality gates
- **Service Authentication**: All services use JWT token authentication
- **Secrets Management**: Never commit secrets - use `container-startup.yml` for local dev config
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
- **ensure_jwt_keys fixture**: JWT authentication for service tests
- **Service fixtures**: Auto-depend on JWT keys for authentication

### Git Workflow Patterns
- Squash related commits into logical units
- Use `git commit --amend` for iterative fixes
- Professional commit messages despite colorful conversation
- Always give Claude co-author credit in commits

### Pull Request Guidelines
- **ALWAYS check for PR templates** in both the aap-gateway repo and django-ansible-base repo
  - Look for `.github/pull_request_template.md` or `.github/PULL_REQUEST_TEMPLATE.md`
  - Follow the template structure if one exists
- **PR titles MUST be prefixed with JIRA number**: `[AAP-1234] Description of changes`
  - If JIRA number is not known, **STOP and prompt the user** for the JIRA ticket number
  - Never create a PR without the JIRA prefix

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

## JIRA Ticket Creation

### Default Project Settings

#### Project Key
- **Default**: `AAP` (Ansible Automation Platform)
- Always assume `AAP` project unless explicitly specified otherwise
- All commit messages and PR titles should include `[AAP-XXXXX]` prefix

When using MCP JIRA tools to create and update tickets programmatically:

### Workstream Custom Field
The **Workstream** field is a custom field that requires special handling:
- Field ID: `customfield_12319275`
- Type: Multi-select (array of options)
- Use `mcp_atlasian_jira_search_fields` with keyword "workstream" to find field details

### Creating Issues with Workstream
**Important:** Workstream cannot be set during the `create_issue` call and must be updated after creation:

```python
# Step 1: Create the issue
mcp_atlasian_jira_create_issue(
    project_key="AAP",
    summary="Your summary",
    issue_type="Story",
    description="Your description",
    components="cicd"
)

# Step 2: Add Workstream after creation
mcp_atlasian_jira_update_issue(
    issue_key="AAP-12345",
    fields={},
    additional_fields={
        "customfield_12319275": [{"value": "Installers and Productization"}]
    }
)
```

**Common Workstream Values:**
- "Installers and Productization"
- "UI/UX"
- "API Development"

**Tip:** Always use `mcp_atlasian_jira_search_fields` to discover custom field IDs when needed.

### Bug-Specific Rules

When creating or working with bugs:

1. **Bug Creation Workaround**: Due to MCP limitations, create bugs as Stories first, then convert
   - Create as `issue_type="Story"`
   - Immediately convert to Bug using `update_issue` with `{"issuetype": {"name": "Bug"}}`
   - This is required for reliable bug creation

2. **Story Points**: Always set to `0`
   - Bugs are reactive work and don't get estimated
   - This is a hard requirement, not a suggestion
   - Use: `{"customfield_12310243": 0}`

3. **Acceptance Criteria**: Required for transitioning to In Progress
   - Must include clear, measurable acceptance criteria in the description
   - Without acceptance criteria, the transition will fail
   - Use: `{"customfield_12315940": "criteria text"}`

4. **Example Bug Creation**:
```python
# Step 1: Create as Story (workaround for MCP bug creation issues)
issue = mcp_atlasian_jira_create_issue(
    project_key="AAP",
    summary="[Bug] Description of issue",
    issue_type="Story",  # Create as Story first!
    description="""
## Problem
Describe the bug...

## Expected Behavior
What should happen...

## Actual Behavior
What actually happens...

## Steps to Reproduce
1. Step one
2. Step two
3. Bug occurs

## Acceptance Criteria
* Bug is fixed and verified
* Tests pass consistently
* No regression in related functionality
    """
)
issue_key = issue["issue"]["key"]

# Step 2: Convert to Bug
mcp_atlasian_jira_update_issue(
    issue_key=issue_key,
    fields={"issuetype": {"name": "Bug"}}
)

# Step 3: Always set story points to 0 for bugs
mcp_atlasian_jira_update_issue(
    issue_key=issue_key,
    additional_fields={"customfield_12310243": 0}
)

# Step 4: If fixing it, move to In Progress (acceptance criteria must be present!)
mcp_atlasian_jira_transition_issue(
    issue_key=issue_key,
    transition_id=41  # "In Progress"
)
```

### Status Management Rules

**Critical Rule**: If you are taking action on a ticket (coding, creating PRs, making changes), it **MUST** be transitioned to "In Progress".

This ensures:
- The board accurately reflects active work
- Team visibility into what's being worked on
- Proper workflow tracking

**Prerequisites for Transitioning to In Progress:**
- Acceptance Criteria MUST be present in the description (use `customfield_12315940`)
- Sprint SHOULD be set (use `customfield_12310940`)
- Without acceptance criteria, the transition will fail

**Workflow States:**
- **New/To Do**: Not started
- **In Progress**: Actively being worked on (required when taking action)
- **Review**: PR created, awaiting review
- **Done**: Merged and complete

### Known MCP JIRA Tool Limitations

**Issue Type Selection:**
- Direct `issue_type="Bug"` creation may fail in some cases
- Use the Story → Bug conversion workflow documented above
- This workaround is reliable and allows full bug field configuration

**Fields That Work via API (with correct formats):**
- ✅ **Components**: Use `{"components": [{"name": "aap-gateway"}]}`
- ✅ **Story Points**: Use `{"customfield_12310243": 0}` (number, not string)
- ✅ **Workstream**: Use `{"customfield_12319275": [{"value": "Platform Services"}]}`
- ✅ **Assignee**: Use simple string format: `{"assignee": "jowestco@redhat.com"}` (email works best)
- ✅ **Priority**: Use `{"priority": {"name": "Major"}}` (or "Critical", "High", "Normal", "Low")
- ✅ **Acceptance Criteria**: Use `{"customfield_12315940": "text content"}` (plain text or newline-separated list)
- ✅ **Sprint**: Use `{"customfield_12310940": 77833}` (plain number, NOT array, NOT string)
- ✅ **Status Transitions**: Use `transition_issue` with valid transition ID (ensure all required fields are set first)

**Recommended Workflow:**
1. Create the issue with minimal required fields (project, summary, type, description)
2. Note the created issue key (e.g., AAP-58187)
3. Update fields one at a time using the working formats above
4. Set Sprint (required for status transitions like "In Progress")
5. Transition the issue to desired status (e.g., "In Progress")
6. All fields can now be set programmatically!

**Example: Complete Ticket Creation Workflow:**
```python
# Step 1: Create the issue (minimal fields)
issue = mcp_atlasian_jira_create_issue(
    project_key="AAP",
    summary="Your issue summary",
    issue_type="Story",
    description="Your detailed description"
)
issue_key = issue["issue"]["key"]  # e.g., "AAP-58187"

# Step 2: Update components
mcp_atlasian_jira_update_issue(
    issue_key=issue_key,
    fields={"components": [{"name": "aap-gateway"}]}
)

# Step 3: Update workstream (custom field)
mcp_atlasian_jira_update_issue(
    issue_key=issue_key,
    fields={},
    additional_fields={"customfield_12319275": [{"value": "Platform Services"}]}
)

# Step 4: Update story points (custom field)
mcp_atlasian_jira_update_issue(
    issue_key=issue_key,
    fields={},
    additional_fields={"customfield_12310243": 0}
)

# Step 5: Assign to user (use email)
mcp_atlasian_jira_update_issue(
    issue_key=issue_key,
    fields={"assignee": "jowestco@redhat.com"}
)

# Step 6: Set priority
mcp_atlasian_jira_update_issue(
    issue_key=issue_key,
    fields={"priority": {"name": "Major"}}
)

# Step 7: Add acceptance criteria
acceptance_criteria = """- Remove @pytest.mark.django_db from teams fixture
- Remove @pytest.mark.django_db from users fixture
- Verify tests pass locally with single-threaded tox run
- Verify CI tests pass without PytestRemovedIn9Warning"""
mcp_atlasian_jira_update_issue(
    issue_key=issue_key,
    fields={},
    additional_fields={"customfield_12315940": acceptance_criteria}
)

# Step 8: Set sprint (get sprint ID from board first)
# Use mcp_atlasian_jira_get_sprints_from_board to find the active sprint ID
sprint_id = 77833  # Example: Platform Services 2025-44
mcp_atlasian_jira_update_issue(
    issue_key=issue_key,
    fields={},
    additional_fields={"customfield_12310940": sprint_id}
)

# Step 9: Transition to In Progress (get transition ID from get_transitions)
mcp_atlasian_jira_transition_issue(
    issue_key=issue_key,
    transition_id=41  # "In Progress" transition ID
)

print(f"✅ Ticket fully configured: https://issues.redhat.com/browse/{issue_key}")
print(f"   Status: In Progress | Sprint: Set | All fields configured!")
```

**Status Transitions:**

To transition issues between states, first get available transitions, then use the transition ID:

```python
# Get available transitions for an issue
transitions = mcp_atlasian_jira_get_transitions(issue_key="AAP-58187")
# Returns: [{"id": 11, "name": "New"}, {"id": 41, "name": "In Progress"}, ...]

# Transition the issue (with optional comment)
mcp_atlasian_jira_transition_issue(
    issue_key="AAP-58187",
    transition_id=141,  # "Review" transition ID
    comment="CI checks passed. Moving to Review."
)
```

**Common Transition IDs** (may vary by project):
- `11` - New
- `71` - Refinement
- `81` - Backlog
- `41` - In Progress
- `141` - Review
- `131` - Release Pending
- `61` - Closed

**Note:** Always use `get_transitions` to get valid transition IDs for a specific issue, as available transitions depend on the issue's current state and workflow configuration.

**Custom Field Discovery:**
```bash
# Find Story Points field
mcp_atlasian_jira_search_fields --keyword "story points" --limit 5

# Find Sprint field
mcp_atlasian_jira_search_fields --keyword "sprint" --limit 5

# Find Workstream field
mcp_atlasian_jira_search_fields --keyword "workstream" --limit 5
```

**Key Custom Field IDs:**
- Story Points: `customfield_12310243`
- Sprint: `customfield_12310940`
- Workstream: `customfield_12319275`
- Acceptance Criteria: `customfield_12315940`

## Additional Resources

For user-specific preferences and instructions, check `AGENTS_USER.md` if it exists in the repository.
