# Automation Hub/Galaxy Development

Automation Hub/Galaxy is a plugin to the Pulp project.
It's being deployed by the oci-env utility.  
Galaxy_ng project has the Makefile, but running docker-compose through it is deprecated.

## Assumptions

All repositories are cloned to the `<your-path>/aap` folder, hereinafter referred to as `aap folder`. 

## Repositories

Clone into `aap folder`:
- upstream:
  - https://github.com/ansible/galaxy_ng 
    - `git clone git@github.com:ansible/galaxy_ng.git`
- dev installer
  - https://github.com/pulp/oci_env 
    - `git clone git@github.com:pulp/oci_env.git`
- pulp
  - https://github.com/pulp/pulpcore (optional)
  - https://github.com/pulp/pulp_ansible (optional)
- analytics package:
  - https://github.com/RedHatInsights/insights-analytics-collector

## Installation

### Before installation

Create `compose.env`:
- `cd <aap folder>/oci-env`
- `cp ./compose.env.example ./compose.env`
- Content of the `compose.env` could look like this:

```yaml
COMPOSE_PROJECT_NAME='oci_env-standalone'
COMPOSE_PROFILE=galaxy_ng/base
#DEV_SOURCE_PATH=pulpcore:pulp_ansible:galaxy_ng
DEV_SOURCE_PATH=galaxy_ng

COMPOSE_BINARY=docker
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_PASSWORD=admin
ENABLE_SIGNING=1
SETUP_TEST_DATA=1
UPDATE_UI=0

PULP_GALAXY_REQUIRE_CONTENT_APPROVAL=false
# /api/galaxy/ by default
PULP_GALAXY_API_PATH_PREFIX='/api/hub/'

PULP_ANSIBLE_COLLECT_DOWNLOAD_LOG=True
PULP_ANSIBLE_COLLECT_DOWNLOAD_COUNT=True

#PULP_GALAXY_FEATURE_FLAGS__ai_deny_index=true
#PULP_GALAXY_ENABLE_LEGACY_ROLES=true

#PULP_CONNECTED_ANSIBLE_CONTROLLERS='["https://controller.example.com"]'
PULP_GALAXY_METRICS_COLLECTION_AUTOMATION_ANALYTICS_ENABLED=True
PULP_GALAXY_METRICS_COLLECTION_C_RH_C_UPLOAD_URL="http://automation-analytics-backend_ingress_1:3000/api/ingress/v1/upload"
PULP_GALAXY_METRICS_COLLECTION_AUTOMATION_ANALYTICS_AUTH_TYPE="x-rh-identity"
PULP_GALAXY_METRICS_COLLECTION_ORG_ID="0000001"

```

### Installation steps

- init [virtualenv](#virtual-env)
- create oci_env
  - `cd <aap folder>/oci_env`
  - `pip install -e client/`
- `oci_env compose build`

### Virtual Env

```shell
cd <aap folder>/galaxy_ng
mkdir -p ../venv
python -m venv ../venv/galaxy_ng
source ../venv/galaxy_ng/bin/activate 
python -m pip install -r dev_requirements.txt 
python -m pip install -r docs_requirements.txt 
python -m pip install -r integration_requirements.txt 
# python -m pip install -e .  # optional 
```

### Project installation docs

Old one (but still useful):
- https://github.com/ansible/galaxy_ng/wiki/Development-Setup
 
New one:
- https://ansible.readthedocs.io/projects/galaxy-ng/en/latest/community/devstack/ 
- https://ansible.readthedocs.io/projects/galaxy-ng/en/latest/dev/docker_environment/ 

## Run backend

- `oci-env compose up`

### Seed data

- https://github.com/himdel/ansible-hub-ui/wiki/Getting-Data 
- Run on localhost (not in container), it connects to http://localhost:5001:
```shell
pip install galaxykit ; galaxykit collection upload <my_namespace> <my_name>
```

Collection example:
- https://galaxy.ansible.com/ansible/network
- https://galaxy.ansible.com/community/dns

*TODO*: Generated data

### API

The path is specified by `PULP_GALAXY_API_PATH_PREFIX` defined in `compose.env` above.  
If not, default prefix is `/api/galaxy`
- http://localhost:5001/api/hub/
- http://localhost:5001/api/hub/v3/plugin/ansible/content/published/collections/
- http://localhost:5001/api/hub/pulp/api/v3/status/

**Credentials**:  
Specified by `DJANGO_SUPERUSER_USERNAME` and `DJANGO_SUPERUSER_PASSWORD` defined in `compose.env` above:
- user: `admin`
- password: `admin`

### Bash

- `docker exec -it oci_env-standalone_pulp_1 /bin/bash`

### Postgres

From localhost:
- not available 

From bash:
- [Go to bash](#bash)
- `psql -U postgres -d pulp`

## Run UI

TODO

## Run tests

TODO

