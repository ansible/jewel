# SonarQube Cloud in AAP-Gateway

SonarQube Cloud (formerly known as SonarCloud) is a **Software-as-a-Service (SaaS)** code analysis tool that helps maintain high-quality code by identifying issues related to maintainability, reliability, and security. 

We use SonarQube Cloud to perform code analysis on main branch, pull and push requests to ensure a certain level of code coverage and compliance with quality code standards.

## 🔹 Core Concepts in SonarQube Cloud

1. **Clean as You Code**:
A development practice ensuring that **new code** complies with quality standards.  

2. **Clean Code Attributes**: Consistency, Intentionality, Adaptability and Responsibility.
    - 📚 [Code analysis metrics](https://docs.sonarsource.com/sonarqube-cloud/digging-deeper/metric-definitions/)

3. **Software Quality**: SonarQube Cloud assesses software quality by detecting issues that violate clean code principles. Each issue impacts one or more software qualities with varying severity.  
    - 📚 [Code analysis based on clean code](https://docs.sonarsource.com/sonarqube-cloud/core-concepts/clean-code/code-analysis/)

4. **Quality Standards**: is made up of a quality profile and a quality gate.
    - *Quality Profile* – A set of rules applied during analysis.  
    - *Quality Gate* – A set of conditions that must be met for the code to pass code quality standards. 
   The gate shows pass (green) or fail (red) status based on whether all conditions are met or if any condition is not met. 


## 🔍 SonarQube Cloud  Analysis Methods

For **GitHub repositories**, SonarQube Cloud supports two analysis methods:

### 1️⃣ [**Automatic Analysis**](https://docs.sonarsource.com/sonarqube-cloud/advanced-setup/automatic-analysis/)  
- Requires no configuration in the repository.  
- Analysis runs directly on **SonarCloud’s platform**.  

- ❌ **Limitations**:
  - Not all repositories qualify.
  - Branch analysis of non-pull request branches other than the main branch is not supported.
  - Code coverage information is not supported.
- Example: `ansible/awx` uses **automatic analysis**.

### 2️⃣ [**CI-Based Analysis**](https://docs.sonarsource.com/sonarqube-cloud/advanced-setup/ci-based-analysis/overview-of-integrated-cis/)

- *SonarScanner* is installed as part of the build process and performs the actual code analysis in the build environment. 
- Provides customized configuration options.
- To include [***code coverage***](https://docs.sonarsource.com/sonarqube-cloud/enriching/test-coverage/overview/): A code coverage tool needs to be set up and run *before* the SonarScanner analysis step so that Sonar can import the code coverage report files.  
- Results are uploaded to SonarCloud after execution.

## ⚙️ How SonarCloud is Configured in AAP-Gateway

AAP-Gateway uses CI-based analysis with GitHub Actions (GHA) to integrate SonarCloud while incorporating code coverage data.

> [!NOTE]
> Some of the links below require authentication to SonarCloud. If you see a blank page after clicking a link, use the login option in the upper right corner. If the page remains blank, you may not have permission to view the data.

### 🔹 AAP-Gateway Quality Standards:
AAP-Gateway uses the default "Sonar Way" Quality Profile and applies a Quality Gate to enforce coding standards.
This ensures that any introduced changes meet defined thresholds for maintainability, reliability, and security.

- 📚 [aap-gateway Quality Profile](https://sonarcloud.io/project/information?id=ansible_aap-gateway)
- 📚 [aap-gatewat Quality Gate](https://sonarcloud.io/organizations/ansible/quality_gates/show/118786)

### 🔹 Project Analysis Configuration and Parameters:
In general, project analysis settings can be configured in 3 different places: in the UI, in a configuration file, or on the command line.

For CI-based analysis, parameters can be set in the `sonar-project.properties` file.

- 📚 [aap-gateway `sonar-project.properties`](https://github.com/ansible/aap-gateway/blob/devel/sonar-project.properties)
- 📚 [Setting configuration with analysis parameters](https://docs.sonarsource.com/sonarqube-cloud/advanced-setup/analysis-parameters/#setting-configuration-in-a-file)

> [!WARNING] 
> If changes to `sonar-project.properties` break SonarCloud, the PR may still appear **green** since Sonar doesn't inject itself in such cases.

## 📌 GitHub Actions Integration  
There are two GitHub Actions workflows that handle the integration of SonarCloud into the AAP-Gateway CI/CD pipeline:  

SonarCloud analysis on PRs to private repositories requires a special setup because PR workflows don’t have access to secrets. To solve this, we trigger the SonarCloud workflow (`sonar-pr.yml`) after the main CI workflow completes. This workflow runs in the upstream repository context, so it has access to the necessary secrets and can report results back to the PR.

### 🔹 **1. CI Workflow**
File: [`.github/workflows/ci.yml`](https://github.com/ansible/aap-gateway/blob/devel/.github/workflows/ci.yml)  
Trigger: Runs on push and pull requests  

- The CI workflow first using `tox` with `pytest` and `pytest-cov` to run tests while measuring code coverage and generating coverage report `coverage.xml`.
- **`coverage.xml`** is then uploaded as an artifact to be used by the `sonar-pr.yml` workflow.  
  📚 GitHub Docs: [Storing & Sharing Data from a Workflow](https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/storing-and-sharing-data-from-a-workflow)

- SonarCloud Scan (on push only, **not** PR): Here, SonarCloud analysis is run only on *direct pushes* to the upstream repository (e.g. when a PR is merged). This step is skipped otherwise.

### 🔹 **2. SonarCloud PR Workflow**
File: [`.github/workflows/sonar-pr.yml`](https://github.com/ansible/aap-gateway/blob/devel/.github/workflows/sonar-pr.yml)  
Trigger: Runs after the CI workflow successfully completes on a pull request  

- Downloads the `coverage.xml` artifact from the CI workflow.
- Retrieves PR metadata, including the base branch.
- Runs SonarCloud scan analysis on the PR.


> [!NOTE]
> *It is important to notice the use of `workflow_run` instead of `pull_request` on trigger condition.*
> 
> GitHub Actions workflows triggered by `pull_request` run in the context of the forked repository, which does not have access to secrets (e.g., the SonarCloud secrets).
>
> By using `workflow_run`:
> - The CI workflow first runs and generates a coverage report.
> - The Sonar PR workflow then executes SonarCloud analysis with the correct permissions, since `workflow_run` runs in the context of the upstream repository (which has access to secrets).
> 
> 📚 GitHub Docs: 
> - [`workflow_run` event in GitHub Actions](https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#workflow_run)
> - [Using secrets in a workflow](https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions#using-secrets-in-a-workflow)


 **📌 Summary: Why Two Workflows?**

| **Workflow**     | **Trigger**       | **Runs SonarCloud?** | **Access to Secrets?** |
|------------------|------------------|----------------------|------------------------|
| `ci.yml`        | Push, PR          | ✅ **Only on push**  | ❌ **Not on PRs** (forks lack access) |
| `sonar-pr.yml`  | After CI success  | ✅ **Only on PRs**   | ✅ **Has access to secrets** |


## 🛠️ Debugging SonarCloud Issues

### 🔹 **Common Issue: Broken `sonar-project.properties`**
If a change in `sonar-project.properties` breaks SonarCloud, debugging can be tricky since the PR may still appear **green** because Sonar doesn't inject itself in such cases. The best approach is to run **`sonar-scanner` locally**.

### 🔹 **Steps to Debug Locally**

1. **Download SonarScanner**  
📚 [SonarScanner Download](https://docs.sonarsource.com/sonarqube/9.9/analyzing-source-code/scanners/sonarscanner/)  

2. **Set up SonarScanner CLI**

   SonarScanner CLI can be used with SonarCloud to debug and configure local analysis. 
   After you have downloaded the SonarScanner archive, follow [this instructions](https://docs.sonarsource.com/sonarqube-cloud/advanced-setup/ci-based-analysis/sonarscanner-cli/) to finish the set up.
   
   > [!NOTE]
   > The extracted `sonar-scanner` files **must stay together**. You **cannot** move only `bin/sonar-scanner` to `/usr/local/bin/`.
   Instead, add the `bin` directory to `$PATH`:

      ```sh
      export PATH=$(pwd)/bin:$PATH
      ```

   > [!TIP]
   > Some of these changes were based on the SonarCloud GitHub Action: https://github.com/SonarSource/sonarcloud-github-action/blob/master/action.yml

3. **Obtain a SonarCloud API Token**
   - Log in to **SonarCloud**  
   - Click your avatar (top-right) → **My Account** → [**Security Tab**](https://sonarcloud.io/account/security)  
   - Generate a new **Sonar Token** and set it as an environment variable:

   ```sh
   export SONAR_TOKEN=your_token_here
   ```

4. **Run SonarScanner Manually**

   Run the command `sonar-scanner` from the project base directory to run the analysis
   ```sh
   sonar-scanner -Dsonar.projectBaseDir=. -Dsonar.host.url=https://sonarcloud.io
   ```

5. **Check for Errors**
   - Most issues appear at the **bottom of the output**.
   - Fix any configuration problems and rerun `sonar-scanner`.
   - You can iterate as quickly as you like, then commit the fix.

## 🔧 Automated Local Analysis Script

For easier PR analysis, we provide an automated script that uses the GitHub CLI to retrieve PR information and run the analysis with the correct parameters.

The script follows the [thenets/bash-helpers](https://github.com/thenets/bash-helpers) boilerplate pattern with structured logging, self-documenting help, and robust error handling.

### 🔹 **Quick Start**

```bash
# Setup (one-time)
export SONAR_TOKEN=your_token_here
gh auth login

# Run analysis for current PR branch
./tools/scripts/run-sonar-local.sh

# Or analyze a specific PR number
./tools/scripts/run-sonar-local.sh 123

# View comprehensive help
./tools/scripts/run-sonar-local.sh --help
```

### 🔹 **Features**

- **Auto PR Detection**: Automatically detects current PR or accepts PR number argument
- **GitHub CLI Integration**: Retrieves PR metadata (base branch, head branch, SHA) via `gh`
- **Coverage Generation**: Generates coverage.xml if missing (requires pytest)
- **Exact CI Simulation**: Uses identical sonar-scanner parameters as GitHub Actions workflow
- **Structured Logging**: Color-coded output with `[INFO]`, `[SUCCESS]`, `[WARNING]`, `[ERROR]` levels
- **Self-Documenting**: Help text extracted from script header comments
- **Prerequisite Validation**: Checks all required tools and environment variables
- **Robust Error Handling**: Clear error messages and troubleshooting guidance

### 🔹 **Requirements**

- `SONAR_TOKEN` environment variable  
- GitHub CLI (`gh`) authenticated
- `jq` for JSON parsing
- `sonar-scanner` in PATH
- Optional: `pytest` with `pytest-cov` for coverage generation

### 🔹 **Output Example**

```
---- SonarCloud Local Analysis Tool ----
[INFO ] Checking prerequisites...
[SUCCESS] All prerequisites met
[SUCCESS] Found PR #1
[INFO ]   Head branch: AAP-49383
[INFO ]   Base branch: stable-2.5
[SUCCESS] SonarCloud analysis completed successfully!
```

## 📌 References

- [SonarCloud Documentation](https://docs.sonarsource.com/sonarqube-cloud/)
- [GitHub Actions for SonarCloud](https://docs.sonarsource.com/sonarqube-cloud/advanced-setup/ci-based-analysis/github-actions-for-sonarcloud/)
- [GitHub Workflow Data Sharing](https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/storing-and-sharing-data-from-a-workflow)
