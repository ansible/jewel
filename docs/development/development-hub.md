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

### Installation steps

- init [virtualenv](#virtual-env)
- create oci_env
  - `cd <aap folder>/oci_env`
  - `pip install -e client/`
- `oci_env compose build`

## Run backend

- `cd aap/galaxy_ng`
- `make oci/dab`

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

- `docker exec -it oci_env-dab_pulp_1 /bin/bash`

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

