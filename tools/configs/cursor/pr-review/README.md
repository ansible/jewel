# Cursor CLI Configuration for PR Reviews

## Purpose

This directory contains Cursor CLI configuration for automated pull request reviews in GitHub Actions workflows.

**Prerequisites:**
- A `.github_mcp_env` file in the repository root containing:
  ```
  GITHUB_PERSONAL_ACCESS_TOKEN=your_github_personal_access_token
  ```
  This file provides authentication for the GitHub MCP server. Ensure it's in `.gitignore` to avoid committing credentials.

The review process:
1. **Pre-flight check**: Verify GitHub MCP is available and configured
2. **Create pending review**: Agent creates a pending review on GitHub
3. **During review**: Agent adds detailed review comments to the pending review using GitHub MCP
4. **Submit review**: Agent submits the pending review with a summary comment
5. **Workflow completion**: All feedback is on GitHub, workflow completes successfully

## Files

### `mcp.json`

Configures the GitHub MCP server for automated pull request reviews.

**Key Configuration:**
- **MCP Server**: Runs GitHub integration in a Docker container
- **Authentication**: Requires a `.github_mcp_env` file with `GITHUB_PERSONAL_ACCESS_TOKEN` set
- **Permissions**: Granted via the `--approve-mcps` flag in the workflow

The Cursor agent has access to:
- GitHub CLI (`gh`) commands for viewing PRs and diffs
- GitHub MCP tools to post review comments directly to PRs
- Read access to repository files for context and analysis

This configuration enables the Cursor agent to:
- View PR metadata using `gh pr view` or GitHub MCP tools
- Retrieve PR diffs using `gh pr diff` or GitHub MCP tools
- Read any file in the repository for context and analysis
- **Create a pending review** on GitHub using GitHub MCP
- **Add review comments to the pending review** as issues are found using GitHub MCP
- **Submit the pending review** with a summary comment using GitHub MCP
- Output error diagnostics to terminal if review cannot be completed

All review feedback is posted directly to GitHub using the pending review workflow - no intermediate files are created.

## Usage

This configuration is automatically applied in the PR review workflows:

1. **`.github/workflows/cursor-pull-request.yml`** - Uses this config directory via `CURSOR_CONFIG_DIR`
2. **`.github/workflows/cursor-pull-request-manual.yml`** - Manual trigger workflow
3. **`.github/workflows/repository-automation-dispatcher.yml`** - Automatic trigger on PR events

Permissions are managed via the `--approve-mcps` flag which grants the Cursor agent access to GitHub MCP tools and other required permissions.

**MCP Verification**: The workflow includes a pre-flight check to verify GitHub MCP is available before attempting the review. If the MCP is not configured or unavailable, the workflow will fail early with a clear error message.

## Local Usage

For information on running PR reviews locally from your development machine, see [`.cursor/README.md`](../../../.cursor/README.md).

## Documentation

For more information about Cursor CLI configuration and permissions:
- [Cursor CLI Documentation](https://cursor.com/docs/cli/reference/configuration)
- [Cursor CLI Permissions](https://cursor.com/docs/cli/reference/permissions)

## Security Considerations

- **Authentication**: The `.github_mcp_env` file contains the `GITHUB_PERSONAL_ACCESS_TOKEN` used by the GitHub MCP server
  - This file must be in `.gitignore` to prevent credential leakage
  - The token should have appropriate scopes (see Prerequisites in `.cursor/README.md`)
- Permissions are managed via the `--approve-mcps` flag which grants access to:
  - `gh` shell access for viewing PR metadata and diffs
  - GitHub MCP tools (`mcp__github__*`) for posting review comments
  - Reading any file in the repository for context and analysis
- The `GH_TOKEN` environment variable (in CI/CD workflows) provides authenticated access to GitHub, scoped to the workflow's permissions
- Review permissions are limited to `contents: read` and `pull-requests: write` in the workflow
- The Cursor agent:
  - Creates a pending review using GitHub MCP
  - Adds review comments to the pending review using GitHub MCP during code analysis
  - Submits the pending review with a summary comment using GitHub MCP
  - Outputs error diagnostics to terminal if unable to complete
- All feedback is posted directly to GitHub using the pending review workflow - no files are written to disk
- The workflow will complete successfully once the pending review is submitted to GitHub
