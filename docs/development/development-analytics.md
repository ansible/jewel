# Automation Analytics Development

Automation Analytics (AA) lives in the console.redhat.com.
Connection with on-premise AAP:
- Controller uploads data to Analytics
- Controller includes On-premise Analytics, requesting Analytics API
- Galaxy uploads data to Analytics (AAP 2.5)

- GitHub org: RedHatInsights (Frontend)
- GitLab org: automation-analytics
- Main GIT branch: `main`
- Docker Python version: `3.9`
- Python dependencies specified by Pipenv (Pipfile)
- Project is using Makefile

## Assumptions

All repositories are cloned to the `<your-path>/aap` folder, hereinafter referred to as `aap folder`. 

## Repositories

Clone to the `aap folder`:
- Analytics main (required)
  - https://gitlab.cee.redhat.com/automation-analytics/automation-analytics-backend
- PDF generator
  - https://gitlab.cee.redhat.com/automation-analytics/pdf-generator
- UI
  - https://github.com/RedHatInsights/tower-analytics-frontend
- Jupyter Notebooks
  - https://gitlab.cee.redhat.com/automation-analytics/automation-analytics-jupyter-notebooks

## Installation

### Before installation

- Login to quay.io for download docker image https://quay.io/repository/cloudservices/pdf-generator  
  - Requires see `cloudservices` organization in `quay.io`
  - Permissions are granted by app-interface:
    - https://gitlab.cee.redhat.com/service/app-interface/-/blob/master/data/teams/insights/users/mslemr.yml
      - `/teams/insights/roles/insights-engineers.yml` should be enough
  - *TODO*: Remove this dependency by default
- Create docker network
  - `sudo groupadd docker`
  - `sudo usermod -aG docker $USER`
  - `sudo docker network create koku_default`
- Login to quay.io for download docker image pdf-generator
  - could be replaced by local image, TODO 
- 
### Main installation

- `make patch_etc_hosts`
- `make build`

### Virtual env

Install Pipenv:
-  `pip install --user pipenv`

Install dependencies:
- `pipenv shell`
- `pipenv sync --dev`

### Project Installation Docs

https://gitlab.cee.redhat.com/automation-analytics/automation-analytics-backend/-/blob/main/README.rst

## Run backend

- all:
  - `make up`
- API + RBAC (minimum for UI)
  - `make ui-with-rbac`
- Complete Backend with Minio/Ingress
  - `make backend-with-rbac`

### Seed data

- `make migrations`
- `make data`

## API

- http://localhost:8004/api/tower-analytics/v1/


