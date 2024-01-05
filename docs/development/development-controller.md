# Automation Controller Development

AWX is upstream project for Automation Controller.

In development mode it's running in docker using docker-compose (tested on v1.29).  
- GitHub org: `ansible`
- Main GIT branch: `devel`
- Docker Python version: 3.9
- Python dependencies specified by requirements.txt (updater.sh)
- Project is using Makefile

## Assumptions

All repositories are cloned to the `<your-path>/aap` folder, hereinafter referred to as `aap folder`. 

## Repositories:  

Clone to the `aap folder`:
- upstream:
  - https://github.com/ansible/awx (required) 
    - `git clone git@github.com:ansible/awx.git`
- dev downstream (?) extension:
  - https://github.com/ansible/tower-packaging
    - `git clone git@github.com:ansible/tower-packaging.git`
- downstream:
  - https://github.com/ansible/tower
- analytics package:
  - https://github.com/RedHatInsights/insights-analytics-collector


## Installation

### Before installation

**Ports**:

*Default port conflicts*:

- port 8888 conflicts with EDA
  - configurable by ENV `AWX_JUPYTER_PORT` 
- port 5432 conflicts with EDA, Gateway, Analytics
  - configurable by ENV `AWX_API_PORT`

```shell
export AWX_PG_PORT=5431
export AWX_JUPYTER_PORT=8887
```

**Settings overrides**:

Create a file `awx/settings/local_overrides.py`. It's excluded from GIT.
It can override settings in `awx/settings/defaults.py` and could look like this:
```shell
INSIGHTS_TRACKING_STATE = True
# URL for On-premise API
AUTOMATION_ANALYTICS_URL = "http://automation-analytics-backend_fastapi_1:8080/api/ingress/v1/upload"
# URL for Upload
# AUTOMATION_ANALYTICS_URL = "http://automation-analytics-backend_ingress_1:3000/api/ingress/v1/upload"
SUBSCRIPTION_USAGE_MODEL = "unique_managed_hosts"
INSIGHTS_AGENT_MIME = "application/vnd.redhat.tower.tower_payload+tgz"

```

### Main Installation

- `make docker-compose-build`

### After installation

- If required, build Automation Analytics [doc](development-analytics.md)
- `docker network connect koku_default tools_awx_1`

### Virtual env

**Prerequisites**

Global: 
- `sudo dnf install gcc openssl-devel bzip2-devel libffi-devel zlib-devel wget make` 

AWX:
- python-ldap: 
  - https://www.python-ldap.org/en/python-ldap-3.4.3/installing.html#build-prerequisites
  - `sudo dnf install "@C Development Tools and Libraries" openldap-devel \
      python3-devel python3-tox \
      lcov clang-analyzer valgrind` 

**Installation**
 
- `mkdir -p <aap folder>/venv`
- `python -m venv <aap folder>/venv/awx`
- `source <aap folder>/venv/awx/bin/activate`
- `pip install -r requirements/requirements_dev.txt`

### Project installation docs

- https://github.com/ansible/awx/blob/devel/tools/docker-compose/README.md

 
## Run Controller/AWX

### Run as AWX (upstream)

- `make docker-compose`
  - (re)generates tools/docker-compose/_sources dir
    - `docker-compose.yml`

### Run as Controller (downstream)

- cd `<aap folder>/tower-packaging`
- `CHECKOUT_PATH=<aap folder>/awx make docker-compose-entitlements`

It needs subscription manifest (uploaded through UI), 
i.e. https://github.com/ansible/aap-qa/blob/devel/files/manifest.zip


## Seed data

This will create a demo project, inventory, and job template:
- `docker exec tools_awx_1 awx-manage create_preload_data`


## Create new admin user

- `docker exec -ti tools_awx_1 awx-manage createsuperuser`

## Endpoints, Access, Credentials

### API

https://localhost:8043/api/  
https://localhost:8043/api/v2/

**Credentials**:
- user: `admin`
- password: see `tools/docker-compose/_source/secrets/admin_password.yml`

### Bash

- `docker exec -it tools_awx_1 /bin/bash`

### Postgres

From localhost: 
- `localhost:5431` 
  - If configured in [before installation](#before-installation)

From docker:
- [Go to bash](#bash)
- `psql -h postgres -p 5432 -d awx -U awx`

Credentials:
- user: `awx`
- password: see `tools/docker-compose/_source/secrets/pg_password.yml`

## Run UI

TODO

## Run tests

TODO