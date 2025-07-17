#!/bin/bash
# run-sonar-local.sh
# Runs SonarCloud analysis locally for a Pull Request using GitHub CLI
#
# This script simulates the exact same SonarCloud workflow that runs in GitHub Actions,
# but executes locally for faster iteration and debugging.
#
# Requirements:
#   - SONAR_TOKEN environment variable set
#   - GitHub CLI (gh) authenticated  
#   - sonar-scanner installed and in PATH
#   - jq for JSON parsing
#   - Git repository with PRs
#
# Usage:
#   ./run-sonar-local.sh [PR_NUMBER] [PROJECT_KEY]
#
# Examples:
#   ./run-sonar-local.sh              # Analyze current PR branch
#   ./run-sonar-local.sh 123          # Analyze PR #123
#   ./run-sonar-local.sh 123 ansible_jewel-debug  # Custom project
#   ./run-sonar-local.sh --help       # Show this help
#
# Environment setup:
#   export SONAR_TOKEN=your_token_here
#   gh auth login
#
# The script will:
#   - Automatically detect the current PR or use provided PR number
#   - Retrieve PR metadata (base branch, head branch, SHA) via GitHub CLI  
#   - Generate coverage data if missing (requires pytest)
#   - Run sonar-scanner with exact same parameters as CI workflow
#   - Provide clear feedback with structured logging
#   - Override project key if provided (useful for forks)
#
# START

# Constants
declare -r SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
declare -r PROJECT_ROOT="$SCRIPT_DIR/../.."
declare -r COVERAGE_FILE="$PROJECT_ROOT/coverage.xml"
declare -r SONAR_URL="https://sonarcloud.io"

# Parameters  
declare -r PR_NUMBER_ARG=${1:-""}
declare -r PROJECT_KEY_ARG=${2:-""}

# Helpers
if [ -z "$TERM" ] || [ "$TERM" == "dumb" ]; then
    function tput() { return 0; }
fi

if ! type tput >/dev/null 2>&1; then
    function tput() { return 0; }
fi

function log_info() {
    local CYAN=$(tput setaf 6)
    local NC=$(tput sgr0)
    echo "${CYAN}[INFO ]${NC} $*" 1>&2
}

function log_warning() {
    local YELLOW=$(tput setaf 3)
    local NC=$(tput sgr0)
    echo "${YELLOW}[WARNING]${NC} $*" 1>&2
}

function log_debug() {
    local PURPLE=$(tput setaf 5)
    local NC=$(tput sgr0)
    echo "${PURPLE}[DEBUG ]${NC} $*" 1>&2
}

function log_error() {
    local RED=$(tput setaf 1)
    local NC=$(tput sgr0)
    echo "${RED}[ERROR ]${NC} $*" 1>&2
}

function log_success() {
    local GREEN=$(tput setaf 2)
    local NC=$(tput sgr0)
    echo "${GREEN}[SUCCESS]${NC} $*" 1>&2
}

function log_title() {
    local GREEN=$(tput setaf 2)
    local BOLD=$(tput bold)
    local NC=$(tput sgr0)
    echo 1>&2
    echo "${GREEN}${BOLD}---- $* ----${NC}" 1>&2
}

function h_run() {
    local ORANGE=$(tput setaf 3)
    local NC=$(tput sgr0)
    echo "${ORANGE}\\$${NC} $*" 1>&2
    eval "$*"
}

function err() {
    echo "[$(date +'%Y-%m-%dT%H:%M:%S%z')]: $*" >&2
}

function print_help() {
    # Prints help section from the top of the file
    # It stops until it finds the '# START' line
    echo "HELP:"
    while read -r LINE; do
        if [[ "${LINE}" == "#!/bin/bash" ]] || [[ "${LINE}" == "" ]]; then
            continue
        fi
        if [[ "${LINE}" == "# START" ]]; then
            return
        fi
        echo "${LINE}" | sed 's/^# / /g' | sed 's/^#//g'
    done <${BASH_SOURCE[0]}
}

# Functions
function check_command() {
    # Check if command exists in PATH
    # Arguments:
    #   1: command_name
    # Returns:
    #   0 if command exists, 1 otherwise
    local cmd=$1
    if ! command -v "$cmd" &> /dev/null; then
        log_error "$cmd is not installed or not in PATH"
        return 1
    fi
    return 0
}

function check_prerequisites() {
    # Validate all required tools and environment
    # Globals:
    #   SONAR_TOKEN
    # Returns:
    #   Exits script if prerequisites not met
    log_info "Checking prerequisites..."
    
    # Check required commands
    local missing_commands=()
    
    check_command "gh" || missing_commands+=("gh")
    check_command "jq" || missing_commands+=("jq") 
    check_command "sonar-scanner" || missing_commands+=("sonar-scanner")
    check_command "git" || missing_commands+=("git")
    
    if [ ${#missing_commands[@]} -gt 0 ]; then
        log_error "Missing required commands: ${missing_commands[*]}"
        log_info "Install missing commands:"
        for cmd in "${missing_commands[@]}"; do
            case $cmd in
                "jq")
                    log_info "  jq: sudo apt install jq  # or your package manager"
                    ;;
                "sonar-scanner")
                    log_info "  sonar-scanner: https://docs.sonarsource.com/sonarqube/9.9/analyzing-source-code/scanners/sonarscanner/"
                    ;;
                "gh")
                    log_info "  gh: https://cli.github.com/"
                    ;;
            esac
        done
        exit 1
    fi
    
    # Check if we're in a git repository
    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        log_error "Not in a git repository"
        exit 1
    fi
    
    # Check if gh is authenticated
    if ! PAGER="" GH_PAGER="" gh auth status &> /dev/null; then
        log_error "GitHub CLI not authenticated"
        log_info "Run: gh auth login"
        exit 1
    fi
    
    # Check for SONAR_TOKEN
    if [ -z "$SONAR_TOKEN" ]; then
        log_error "SONAR_TOKEN environment variable is required"
        log_info "Get your token from: SonarCloud → Avatar → My Account → Security"
        exit 1
    fi
    
    log_success "All prerequisites met"
}

function get_pr_info() {
    # Retrieve PR information from GitHub CLI
    # Arguments:
    #   1: pr_number (optional)
    # Globals:
    #   Sets PR_NUMBER, PR_BASE, PR_HEAD, HEAD_SHA
    # Returns:
    #   Exits script if PR not found
    local pr_arg=$1
    
    log_info "Retrieving PR information..."
    
    # Get current branch
    local current_branch=$(git branch --show-current)
    log_debug "Current branch: $current_branch"
    
    # Try to get PR number for current branch or use provided number
    local pr_info=""
    if [ -n "$pr_arg" ]; then
        log_info "Using provided PR number: $pr_arg"
        pr_info=$(PAGER="" GH_PAGER="" gh pr view "$pr_arg" --json number,baseRefName,headRefName,headRefOid 2>/dev/null || echo "")
        if [ -z "$pr_info" ]; then
            log_error "PR #$pr_arg not found"
            exit 1
        fi
    else
        pr_info=$(PAGER="" GH_PAGER="" gh pr view --json number,baseRefName,headRefName,headRefOid 2>/dev/null || echo "")
        if [ -z "$pr_info" ]; then
            log_error "No PR found for current branch '$current_branch'"
            log_info "Either checkout a branch with an open PR, or provide a PR number as argument"
            log_info "Usage: $0 [pr_number]"
            exit 1
        fi
    fi
    
    # Parse PR information
    PR_NUMBER=$(echo "$pr_info" | jq -r '.number')
    PR_BASE=$(echo "$pr_info" | jq -r '.baseRefName') 
    PR_HEAD=$(echo "$pr_info" | jq -r '.headRefName')
    HEAD_SHA=$(echo "$pr_info" | jq -r '.headRefOid')
    
    log_success "Found PR #$PR_NUMBER"
    log_info "  Head branch: $PR_HEAD"
    log_info "  Base branch: $PR_BASE" 
    log_info "  Head SHA: $HEAD_SHA"
}

function generate_coverage() {
    # Generate coverage data if missing
    # Globals:
    #   COVERAGE_FILE, PROJECT_ROOT
    # Outputs:
    #   Creates coverage.xml if successful
    log_info "Checking for coverage data..."
    
    cd "$PROJECT_ROOT" || {
        log_error "Cannot change to project root: $PROJECT_ROOT"
        exit 1
    }
    
    if [ ! -f "$COVERAGE_FILE" ]; then
        log_warning "coverage.xml not found, attempting to generate..."
        
        # Check if pytest is available
        if command -v pytest &> /dev/null; then
            log_info "Running pytest with coverage..."
            h_run "pytest --cov=aap_gateway_api --cov-report=xml" || {
                log_error "Failed to generate coverage data"
                exit 1
            }
            log_success "Coverage data generated"
        else
            log_warning "pytest not found, proceeding without coverage data"
            log_info "Install pytest and pytest-cov for coverage generation"
        fi
    else
        log_success "Found existing coverage.xml"
    fi
}

function run_sonar_analysis() {
    # Execute sonar-scanner with PR parameters
    # Globals:
    #   PR_NUMBER, PR_HEAD, PR_BASE, HEAD_SHA
    #   SONAR_URL, PROJECT_ROOT, PROJECT_KEY_ARG
    # Returns:
    #   Exits script if analysis fails
    log_title "Starting SonarCloud Analysis"
    
    cd "$PROJECT_ROOT" || {
        log_error "Cannot change to project root: $PROJECT_ROOT"
        exit 1
    }
    
    # Determine project key - use override if provided, otherwise read from sonar-project.properties
    local project_key=""
    if [ -n "$PROJECT_KEY_ARG" ]; then
        project_key="$PROJECT_KEY_ARG"
        log_info "Using custom project key: $project_key"
    else
        # Read from sonar-project.properties
        if [ -f "sonar-project.properties" ]; then
            project_key=$(grep "^sonar.projectKey=" sonar-project.properties | cut -d'=' -f2)
            log_info "Using project key from sonar-project.properties: $project_key"
        else
            log_error "No sonar-project.properties found and no project key provided"
            exit 1
        fi
    fi
    
    # Build dynamic project URL
    local sonar_project_url="$SONAR_URL/project/pull_requests_list?id=$project_key"
    
    # Build sonar-scanner arguments
    local sonar_args=(
        "-Dsonar.projectBaseDir=."
        "-Dsonar.host.url=$SONAR_URL"
        "-Dsonar.scm.revision=$HEAD_SHA"
        "-Dsonar.pullrequest.key=$PR_NUMBER"
        "-Dsonar.pullrequest.branch=$PR_HEAD"
        "-Dsonar.pullrequest.base=$PR_BASE"
    )
    
    # Add project key override if provided
    if [ -n "$PROJECT_KEY_ARG" ]; then
        sonar_args+=("-Dsonar.projectKey=$project_key")
    fi
    
    log_info "Executing sonar-scanner with PR parameters..."
    log_debug "Arguments: ${sonar_args[*]}"
    
    # Run sonar-scanner
    if h_run "sonar-scanner ${sonar_args[*]}"; then
        log_success "SonarCloud analysis completed successfully!"
        log_info "View results: $sonar_project_url"
    else
        log_error "SonarCloud analysis failed"
        log_info "Check the output above for error details"
        exit 1
    fi
}

# Main
function main() {
    # Main execution function
    # Arguments:
    #   All script arguments
    local args=("$@")
    
    log_title "SonarCloud Local Analysis Tool"
    
    # Handle help flag
    if [ "${args[0]}" = "-h" ] || [ "${args[0]}" = "--help" ]; then
        print_help
        exit 0
    fi
    
    # Check all prerequisites
    check_prerequisites
    
    # Get PR information  
    get_pr_info "$PR_NUMBER_ARG"
    
    # Generate coverage if needed
    generate_coverage
    
    # Run the analysis
    run_sonar_analysis
    
    log_success "Analysis complete! 🎉"
    log_info "Check SonarCloud for detailed results and quality gate status"
}

# Script execution
if [[ ${BASH_SOURCE[0]} == "${0}" ]]; then
    # Script is being invoked directly instead of being sourced
    main "$@"
fi 