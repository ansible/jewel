### Quick Start
From the root of `aap-gateway`.

`make dev-up`

https://localhost/ `admin` / `admin`
https://localhost/api/controller/v2/me/  <-- After logging in via the gateway this should work
https://localhost:8043/ <-- awx

`make dev-down` to bring it all down

### Implementation Notes

Just in case it is not obvious.

#### Dir Structure

```
aap-gateway/
├── aap-dev						   <-- all the aap developer stuff jammed in here
│   ├── controller_settings.py	   <-- awx settings that makes it controller
│   ├── makefile.mk				   <-- included by parent Makefile
│   ├── README.md				   <-- (you are here)
│   └── smoke.py				   <-- smoke tests for gateway and controller behind gateway
├── aap_gateway_api	               <-- gateway source code
├── awx                            <-- awx git clone location
├── container-startup.yml		   <-- gateway dev env config
├── Makefile					   <-- root Makefile
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

Applying `controller_settings.py` is hacky. I'd imagine the dev env code here will grow and do a LOT of settings overriding so we need a better pattern here.

Each component spins up its own Postgres. We should share a postgres server. I'm thinking some docker-compose command to start all services except postgres. Put all the postgreses and whatever accesses them on their own network.
