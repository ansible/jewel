# Automation Hub/Galaxy Development

Automation Hub/Galaxy is a plugin to the Pulp project.
Galaxy_ng project has the Makefile, where you can run the docker-compose.

## Assumptions

All repositories are cloned to the `<your-path>/aap` folder, hereinafter referred to as `aap folder`.

## Repositories

Clone into `aap folder`:
- upstream:
  - https://github.com/ansible/galaxy_ng
    - `git clone git@github.com:ansible/galaxy_ng.git`
- pulp
  - https://github.com/pulp/pulpcore (optional)
  - https://github.com/pulp/pulp_ansible (optional)
- analytics package:
  - https://github.com/RedHatInsights/insights-analytics-collector

## Installation

### Installation steps

## Run backend

- `cd aap/galaxy_ng`
- `make compose/aap`

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

- `docker exec -it compose-manager-1 /bin/bash`

### Postgres

From bash:
- `docker exec -u postgres -it compose-postgres-1 psql -U galaxy_ng -d galaxy_ng`

## Run UI

TODO

## Run tests

TODO

