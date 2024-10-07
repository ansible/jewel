### Requirements

#### Fedora

* docker, running on default context (not rootless) (see "How to check if rootless docker")
* dnf install go-task openssl

### Quick Start
From the `aap-dev` directory, run these commands to get started.
The build command will build the eda-server and Gateway dev images.
The AWX image may be pulled from ghcr.

```
docker pull ghcr.io/ansible/awx_devel:devel
make dev-build
make dev-up
```

Services will be available at the following URLs:
```
https://localhost/                                  - Platform UI - admin/admin
https://localhost/api/controller/v2/                - AWX API (through Gateway proxy)
https://localhost/api/eda/v1/                       - EDA API (through Gateway proxy)
http://localhost:8010/api/eda/                      - EDA API (direct access)
https://localhost:8043/api/controller/v2/           - AWX API (direct access)
http://localhost:5001/api/galaxy/_ui/v2/            - Hub API (direct access)
```

Run `make dev-down` to bring it all down

#### Resetting Volumes

Because this runs multiple development environments, we hesitate to give any Makefile
target to clean containers or volumes.
To get a new database, you probably need to reset volumes in _both_ Gateway and the services
because the `service_id` will persist a reference to a value in the old Gateway database.
So resetting volumes may look like the following command, use at your own risk.

```
docker stop $(docker ps -aq); docker rm $(docker ps -aq); docker volume rm $(docker volume ls -q)
```

If it fails to set the Gateway superuser to admin/admin (corresponding to the `tsd.json`),
you may need to `rm container-startup.yml` at the root of the Gateway repo.

#### Bring Your Own Checkouts

By default, this will create new clones in the aap-gateway `services/` directory.
To use existing AWX and eda-server clones, customize the command like this:

```
EDA_REPO=~/repos/eda-server HUB_REPO=~/repos/galaxy_ng AWX_REPO=~/repos/awx COMPOSE_TAG=devel make dev-up
```

It is important you do not include a trailing slash (`/`) for the locations.
The `COMPOSE_TAG` in AWX defaults to your current branch, so exclude this if that is what you want.

Running this will create a new file in your eda-server directory, to ignore that,
in your eda-server directory add it to the local exclude file.

```
echo src/aap_eda/settings/dev_hacked_settings.py > .git/info/exclude
```

### How to check if rootless docker

Right now the only well worn path is NOT rootless docker!

You can check if you are running rootless with the following command:
```
$ docker context ls

NAME            DESCRIPTION                               DOCKER ENDPOINT                                   ERROR
default *       Current DOCKER_HOST based configuration   unix:///var/run/docker.sock
rootless        Rootless mode                             unix:///run/user/1000/docker.sock
```

Switch to default context with

```
docker context use default
```

### Implementation Notes

Just in case it is not obvious.

#### Dir Structure



*UP* - Script to test if dev env is up and healthy
*SETTINGS OVERRIDES* - Django settings overrides to turn the upstream into downstream
*HACK* - One-off hacks that hopefully go away

```
aap-gateway/
├── aap-dev						            <-- aap developer environment (not gateway things)
│   ├── controller_settings_template.py		<-- SETTINGS OVERRIDES
│   ├── awx-up-check.sh						<-- UP
│   ├── eda_settings_template.py			<-- SETTINGS OVERRIDES
│   ├── eda-server-up-check.sh				<-- UP
│   ├── gateway-eda_server-config-hack.py	<-- HACK
│   ├── gateway-up-check.sh					<-- UP
│   ├── Makefile				            <-- Entrypoint for the aap dev env
│   ├── README.md				            <-- (you are here)
│   └── smoke.py				            <-- smoke tests for gateway and controller behind gateway
├── aap_gateway_api	                        <-- gateway source code
├── services                                <-- awx git clone location
├── container-startup.yml		            <-- gateway dev env config
├── Makefile					            <-- root Makefile
```

Feel free to rethink the directory structure and organization here. For example, I would personally prefer if all the components are cloned one directory back. Maybe this could happen when we move this dev env code out of `aap-gateway`.


### Design Notes

We do not want to dictate individual components dev environment decisions. You may end up doing this without knowing. Let me give you one example. Look at the `.awx-settings-hack` in `aap-dev/makefile.mk`. It presumes 1. the container name of `tools_awx_1` 2. the existance of a supervisor task named `tower-processes:awx-uwsgi`. This creates an implicit dependency and forces the `awx` project to be stable on these choices. This implicit dependency can not be known by open-source awx developers and may not be known by open source developers. A red hat dev that makes changes to this path has to submit a pr to this dev env to keep things working. As a developer, this is hindering.

Be mindful of the dependencies you create.


### Random Notes

Long-term all this dev stuff won't live in `aap-gateway`. It will probably live in a repo of its own.

The `-` tells Make "it's ok if this fails, keep going". It's common to fail on the network deletion step since it is shared by both awx and gateway.
```
awx-down: ...
    -docker-compose ...

gateway-down: ...
    -docker-compose ...
```

Target `dev-down`, which brings everything down, works around the issue described above by disconnecting running containers from shared mesh network first and then invoking targets to bring down individual components.

Applying `controller_settings_template.py` is hacky. I'd imagine the dev env code here will grow and do a LOT of settings overriding so we need a better pattern here.

Each component spins up its own Postgres. We should share a postgres server. I'm thinking some docker-compose command to start all services except postgres. Put all the postgreses and whatever accesses them on their own network.
