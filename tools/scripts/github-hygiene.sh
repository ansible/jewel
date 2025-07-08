#!/bin/bash

# GitHub hygiene script - List open PRs and branches older than 6 months

set -euo pipefail

# Colors for output
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly NC='\033[0m' # No Color

# Function to list open PRs older than 6 months
list_old_prs() {
    echo -e "${YELLOW}Open PRs older than 6 months:${NC}"
    echo "----------------------------------------"
    
    # Calculate date 6 months ago
    local older_than
    older_than=$(date -d "6 months ago" +%Y-%m-%d)
    
    # Get PRs and filter by date
    if ! gh pr list --repo ansible/jewel --state open --limit 200 --json number,title,createdAt,state,author | \
        jq -r '.[] | "\(.number)\t\(.state)\t\(.author.login)\t\(.createdAt)\t\(.title)"' | \
        awk -F'\t' -v older_than="${older_than}T00:00:00Z" '$4 < older_than {print $1"\t"$2"\t"$3"\t"$4"\t"$5}' | \
        sort -k4; then
        echo "Failed to retrieve PR information"
        return 1
    fi
}

# Function to list branches older than 6 months
list_old_branches() {
    echo -e "${YELLOW}Branches older than 6 months:${NC}"
    echo "----------------------------------------"
    
    # Calculate date 6 months ago in ISO format
    local older_than
    older_than=$(date -d '6 months ago' -Iseconds)
    
    # Get all branches and check commit dates
    local branch commit_info commit_date author
    if ! gh api repos/:owner/:repo/branches --paginate | jq -r '.[].name'; then
        echo "Failed to retrieve branch information"
        return 1
    fi | while read -r branch; do
        if commit_info=$(gh api repos/:owner/:repo/commits/"${branch}" --jq '{date: .commit.committer.date, author: .commit.author.name}' 2>/dev/null); then
            commit_date=$(echo "${commit_info}" | jq -r '.date')
            author=$(echo "${commit_info}" | jq -r '.author')
            
            if [[ -n "${commit_date}" && "${commit_date}" < "${older_than}" ]]; then
                echo "${commit_date} - ${author} - ${branch}"
            fi
        fi
    done
}

# Main function
main() {
    echo -e "${GREEN}GitHub Hygiene Report${NC}"
    echo "Open PRs and branches older than 6 months"
    echo "=========================================="
    echo ""
    
    # Check if gh CLI is installed
    if ! command -v gh >/dev/null 2>&1; then
        echo -e "${RED}Error: GitHub CLI (gh) is not installed${NC}"
        echo "Please install it from: https://cli.github.com/"
        exit 1
    fi
    
    # Check if jq is installed
    if ! command -v jq >/dev/null 2>&1; then
        echo -e "${RED}Error: jq is not installed${NC}"
        echo "Please install jq to parse JSON responses"
        exit 1
    fi
    
    # Check if we're authenticated with GitHub
    if ! gh auth status >/dev/null 2>&1; then
        echo -e "${RED}Error: Not authenticated with GitHub${NC}"
        echo "Please run: gh auth login"
        exit 1
    fi
    
    # List old PRs
    list_old_prs
    echo ""
    
    # List old branches
    list_old_branches
}

# Run main function
main "$@" 