# Cursor CLI Configuration for PR Reviews

## Purpose

This directory contains Cursor CLI configuration for automated pull request reviews in GitHub Actions workflows.

The review process:
1. **Pre-flight check**: Verify GitHub MCP is available and configured
2. **Create pending review**: Agent creates a pending review on GitHub
3. **During review**: Agent adds detailed review comments to the pending review using GitHub MCP
4. **Submit review**: Agent submits the pending review with a summary comment
5. **Workflow completion**: All feedback is on GitHub, workflow completes successfully

## Files

### `cli-config.json`

Configures permissions and settings for the Cursor CLI agent when performing PR reviews.

**Key Configuration:**
- **Permissions**:
  - **Allow**: `["Shell(gh)", "Read", "mcp__github__*"]` - Grants the Cursor agent permission to:
    - Execute GitHub CLI (`gh`) commands for viewing PRs and diffs
    - Use GitHub MCP tools to post review comments directly to PRs
    - Read any file in the repository to understand context
  - **Deny**: `[]` - No explicitly denied permissions

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

The configuration ensures the Cursor agent has the necessary permissions to interact with GitHub while maintaining security through explicit permission grants.

**MCP Verification**: The workflow includes a pre-flight check to verify GitHub MCP is available before attempting the review. If the MCP is not configured or unavailable, the workflow will fail early with a clear error message.

## Local Usage

For information on running PR reviews locally from your development machine, see [`.cursor/README.md`](../../../.cursor/README.md).

## Documentation

For more information about Cursor CLI configuration and permissions:
- [Cursor CLI Documentation](https://cursor.com/docs/cli/reference/configuration)
- [Cursor CLI Permissions](https://cursor.com/docs/cli/reference/permissions)

## Security Considerations

- The configuration explicitly allows only:
  - `gh` shell access for viewing PR metadata and diffs
  - GitHub MCP tools (`mcp__github__*`) for posting review comments
  - Reading any file in the repository for context and analysis
- All other shell commands and file writes are implicitly denied unless explicitly allowed
- The `GH_TOKEN` environment variable provides authenticated access to GitHub, scoped to the workflow's permissions
- Review permissions are limited to `contents: read` and `pull-requests: write` in the workflow
- The Cursor agent:
  - Creates a pending review using GitHub MCP
  - Adds review comments to the pending review using GitHub MCP during code analysis
  - Submits the pending review with a summary comment using GitHub MCP
  - Outputs error diagnostics to terminal if unable to complete
- All feedback is posted directly to GitHub using the pending review workflow - no files are written to disk
- The workflow will complete successfully once the pending review is submitted to GitHub
