# Event Driven Automation (EDA) Development

- GitHub org: `ansible`
- Main GIT branch: `main`
- Docker Python version: `3.9`
- Python dependencies managed by Poetry
- Project is using Taskfile(task/go-task) instead of Makefile(make) 

## Assumptions

All repositories are cloned to the `<your-path>/aap` folder, hereinafter referred to as `aap folder`. 

## Repositories

- upstream
  - https://github.com/ansible/eda-server (required)
    - `git clone git@github.com:ansible/eda-server.git`
- downstream
  - https://gitlab.cee.redhat.com/ansible/aap-eda-controller/ 
   
  
## Installation

### Before installation

- `sudo dnf install go-task`
- `sudo dnf install libffi-devel`
- `pip install --user poetry`
- `pip install --user pre-commit`
- init virtual environment
---
#### Virtual Env

```shell
cd <aap folder>/
mkdir -p ../venv
python -m venv ../venv/eda-server
source ../venv/eda-server/bin/activate 
```

**Ports**:

*Default port conflicts*:

- port 5432 conflicts with Controller, gateway, Analytics
  - configurable by ENV `EDA_PG_PORT` 
- port 8000 conflicts with gateway
  - configurable by ENV `EDA_API_PORT` 
- port 8888 conflicts with Controller
  - configurable by ENV `EDA_PODMAN_PORT`   

```shell
export EDA_PG_PORT=5433
export EDA_API_PORT=8010
```

### Main Installation

- pre-install pyyaml 
  - TODO: solve in EDA 
  - pyyaml 6.0 is not compatible with cython >=3.0 (6.0.1 should be)
  - https://github.com/yaml/pyyaml/issues/601#issuecomment-1813963845 
    - `pip install "cython<3.0.0" wheel`
    - `pip install "pyyaml==6.0" --no-build-isolation`
- `go-task dev:init`
- `go-task docker:build`

### Project Installation Docs

- https://github.com/ansible/eda-server/blob/main/docs/development.md 

### Run Backend

```shell
go-task docker:up
```

### Seed data

- `task docker -- run api --rm aap-eda-manage create_initial_data`
  - part of `docker:up`

## API

- http://localhost:8010/api/eda/ 


**Credentials**:
  - https://github.com/ansible/eda-server/blob/main/scripts/create_superuser.sh
    - `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD`
  - user: `admin`
  - password: `testpass`


# UI

- https://localhost:8443/eda/dashboard
