# AAP Development HOWTOs

## Installation Documentations

- **Automation Controller**
  - [development-controller.md](./development/development-controller.md)
- **Automation Hub**
  - [development-hub.md](./development/development-hub.md)
- **Event Driven Automation**
  - [development-eda.md](./development/development-eda.md)
- **Gateway**
  - [development-gateway.md](./development/development-gateway.md)
- **Automation Analytics**
  - [development-analytics.md](./development/development-analytics.md)

## APIs

- **Automation Controller**
  - https://localhost:8043/api/v2/
- **Automation Hub**
  - http://localhost:5001/api/hub/v3/
  - http://localhost:5001/api/hub/pulp/api/v3/
- **Event Driven Automation**
  - http://localhost:8010/api/eda/v1/
- **Gateway**
  - https://localhost/api/gateway/v1/settings/proxy/
  - https://localhost/api/controller/v2/projects/
  - https://localhost/api/hub/v3/plugin/ansible/content/published/collections/
  - https://localhost/api/eda/v1/users/
- **Automation Analytics**
  - http://localhost:8004/api/tower-analytics/v1/

## UIs

- **Automation Controller**
  - AWX UI: https://localhost:8043/#/home
  - Platform UI: http://localhost:4101
- **Automation Hub**
  - Hub UI: http://localhost:8002
  - Platform UI: http://localhost:4102
- **Event Driven Automation**
  - EDA UI: https://localhost:8443/eda/dashboard/
  - Platform UI: http://localhost:4103
- **Gateway**
  - https://localhost:8000/

## Credentials

- **Automation Controller**
  - API/UI (generated):
    - user: `admin`
    - pwd: `<awx root>/tools/docker-compose/_sources/secrets/admin_password.yml`
  - Postgres (generated):
    - user: `awx`
    - pwd: `<awx root>/tools/docker-compose/_source/secrets/pg_password.yml`
- **Automation Hub**
  - API/UI: `galaxy_ng/dev/compose/aap.yaml`
    - user: ENV `DJANGO_SUPERUSER_USERNAME`
    - pwd: ENV `DJANGO_SUPERUSER_PASSWORD`
  - Postgres
    - ? TODO
- **Event Driven Automation**
  - API/UI:
    - https://github.com/ansible/eda-server/blob/main/scripts/create_superuser.sh
      - user: `DJANGO_SUPERUSER_USERNAME` (default `admin`)
      - pwd: `DJANGO_SUPERUSER_PASSWORD` (default `testpass`)
  - Postgres:
    - db: eda
    - port: 5430
    - user: postgres
    - pwd: secret
- **Gateway**
  - API/UI (generated):
    - `<gw root>/container-startup.yml`
      - user: gateway_admin_username
      - pwd: gateway_admin_password: admin
  - Postgres:
    - db: gateway
    - port: 5432
    - user: gateway
    - pwd: gateway

## Exposed ports

- **Automation Controller**
  - AWX (`tools_awx_1`):
    - "7899-7999:7899-7999"  # sdb-listen
    - "6899:6899"
    - "8080:8080"  # unused but mapped for debugging
    - "8888:8888"  # jupyter notebook
    - "8013:8013"  # http
    - "8043:8043"  # https
    - "2222:2222"  # receptor foo node
    - "3000:3001"  # used by the UI dev env
  - Postgres (`tools_postgres_1`):
    - (5431->5432) not default
  - Redis (`tools_redis_1`):
    - 6379 (not exposed)-
- **Automation Hub**
  - Galaxy (`compose-manager-1`):
    - "5001:5001"  # http
    - "12345:12345"
- **Event Driven Automation**
  - API:
    - "8010:8000" # 8000 by default (conflict)
  - WS:
    - "8001:8000"
  - UI:
    - "8443:443" # https
  - Postgres:
    - "5433:5432"
  - Redis:
    - "6379:6379"
  - Podman:
    - "8888:8888"
- **Gateway**
  - API:
    - "4444:4444"
    - "8000:8000"
  - Envoy Proxy:
    - "443:9080"
    - "19000:19000"
