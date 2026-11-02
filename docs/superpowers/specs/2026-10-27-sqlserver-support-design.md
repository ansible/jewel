# SQL Server Support Design

## Intent

Run Jewel against Microsoft SQL Server using the custom database backend provided by django-ansible-base (DAB). The first supported deployment shape is a single Gateway instance. PostgreSQL remains the default.

## Why

SQL Server support is being added across AAP components. Jewel needs to run its own models and migrations on SQL Server, and developers need a local Compose profile and CI coverage that exercise that backend.

## Goals

- Allow the configured Django database engine to select `ansible_base.backends.mssql`, with the connection options required by DAB's backend.
- Keep Gateway's PostgreSQL defaults and existing PostgreSQL workflows unchanged.
- Resolve Jewel-owned PostgreSQL assumptions that prevent SQL Server migrations or runtime queries.
- Run the Gateway unit suite against SQL Server through a dedicated tox target and CI job.
- Add an opt-in SQL Server Developer container to the local Compose environment, controlled by `mssql_enabled` in `container-startup.yml`.
- Include the SQL Server ODBC driver in Gateway runtime, development, and CI images.
- Do not change Gateway models or migration files.

## Non-goals

- Multi-node Gateway operation on SQL Server. DAB cache broadcast and dispatcherd are disabled for the SQL Server configuration until SQL Server Service Broker support is ready.
- Production database provisioning or changing the default production database configuration.
- Replacing PostgreSQL for other optional development services such as Keycloak.
- Pinning or changing Jewel's DAB requirement. Local development uses the existing `django-ansible-base/` checkout, and the Jewel PR will declare its DAB PR dependency with a `Requires` line.

## Constraints

- Use DAB's `ansible_base.backends.mssql` backend and its SQL Server compatibility helpers.
- Do not change the DAB requirement in Jewel. The local `django-ansible-base/` checkout supplies the backend during development; the Jewel PR's `Requires` line will select the DAB PR in CI.
- Do not modify Gateway model definitions or migration files.
- Use Microsoft's SQL Server 2025 Developer container image for local development and CI.
- Use ODBC Driver 18 in Gateway images; certificate trust bypass is limited to local development and tests.
- The SQL Server CI job installs ODBC Driver 18 at runtime because PR workflows use the base-branch `jewel-ci` image, which cannot include the change until that image is rebuilt.
- SQL Server supports at most 2100 query parameters. Large role-assignment queries must be chunked below that limit.
- `mssql_enabled` defaults to false. The Compose SQL Server profile must leave the existing PostgreSQL service available for other development containers.

## Design calls

- Select the SQL Server backend through the existing `DATABASE_ENGINE` configuration and pass backend-specific `DATABASE_OPTIONS` as a JSON environment value.
- Replace PostgreSQL `DISTINCT ON` in the Envoy REST control-plane query with a portable window-function query for SQL Server.
- Rewrite secret-key rotation pagination and updates with Django ORM querysets so they use backend-specific limit syntax and JSON adaptation.
- Keep DAB's `bulk_create_db_safe` for PostgreSQL conflict-tolerant inserts. For SQL Server, use parameter-batched `MERGE ... WITH (HOLDLOCK)` statements so inserts remain idempotent without DAB's per-row fallback; split object-role lookups into batches below SQL Server's parameter limit.
- Make the self-managed role-migration cursor table use SQL Server-compatible DDL and upsert SQL when that backend is selected.
- When SQL Server is selected, skip dispatcherd setup and autostart, and disable DAB's distributed cache invalidation. This is safe for the single-node deployment in scope.
- Keep the SQL Server database in a separate Compose service. The PostgreSQL service remains available for Keycloak and remains the selected database when `mssql_enabled` is false.

## Acceptance criteria

- Gateway starts, migrates, serves its normal endpoints, and runs without SQL Server errors when configured with DAB's SQL Server backend.
- SQL Server unit tests and the existing PostgreSQL unit suite pass.
- CI runs the Gateway unit suite against SQL Server.
- The local Compose environment starts the SQL Server profile and Gateway successfully when enabled, while the default PostgreSQL profile remains unchanged.
- Existing perf tests remain usable; SQL Server may be slower than PostgreSQL but must not introduce unbounded query growth or exceed SQL Server's parameter limit.

## Remaining implementation decisions

Use existing Jewel conventions for test settings, tox-managed containers, Compose generation, health checks, and documentation. Add focused regression tests for each PostgreSQL-specific behavior changed above, then run the complete SQL Server tox target and existing PostgreSQL unit suite.
