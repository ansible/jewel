# Gateway development

- GitHub org: `ansible`
- Main GIT branch: `devel`
- Docker Python version: 3.11
- Python dependencies specified by requirements.txt (updater.sh)
- Project is using Makefile 

## Assumptions

All repositories are cloned to the `<your-path>/aap` folder, hereinafter referred to as `aap folder`. 

## Repositories

- https://github.com/ansible/aap-gateway/ (required)
- https://github.com/ansible/django-ansible-base/
  - clone as aap-gateway's subdirectory
- https://github.com/ansible/aap-gateway-service-lib


## Installation
### Before installation

Login to quay.io for download docker image https://quay.io/ansible/platform-ui  
- Requires `quay.io` invitation to “aapgateway” group to see `ansible` organization

Alternatively you can clone https://github.com/ansible/aap-ui.git locally,
and run the image build steps, then set the tag locally.

```bash
npm ci
cd platform
npm run build
cd ..
docker build --file platform/Dockerfile --target platform-ui --tag platform-ui .
docker image tag platform-ui:latest quay.io/ansible/platform-ui:latest
```

These steps will be subject to change later.

### Main installation

- Follow the [Readme](#project-installation-docs)
- Update content of `proxy.yml`:
```yaml
services:
  gateway:
    use_tls: true
    api_port: 8000
    control_plane_port: 50051
    service_root: /
    type: gateway
    order: 100
    nodes:
      - address: "gateway"

  hub:
    use_tls: false
    service_root: /api/hub/
    api_port: 5001
    type: hub
    order: 1
    nodes:
      - address: "localhost"

  controller:
    use_tls: true
    service_root: /api/
    api_port: 8043
    type: controller
    order: 2
    nodes:
      - address: "localhost"

  eda:
    use_tls: false
    service_root: /api/eda/
    api_port: 8010
    type: eda
    order: 3
    nodes:
      - address: "localhost"

```

### Virtual env

**Prerequisites**

Global: 
- `sudo dnf install gcc openssl-devel bzip2-devel libffi-devel zlib-devel wget make` 

**Installation**
 
- `mkdir -p <aap folder>/venv`
- `python -m venv <aap folder>/venv/aap-gateway`
- `source <aap folder>/venv/aap-gateway/bin/activate`
- `pip install -r requirements/requirements_dev.txt`

### Project Installation Docs

- https://github.com/ansible/aap-gateway/blob/devel/README.md

## Run

- `make docker-compose`

## API/UI/Credentials:

see [main development page](../development.md)
