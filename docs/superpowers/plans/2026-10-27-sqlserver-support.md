# SQL Server Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run Jewel and its full unit suite on SQL Server through DAB's custom backend, with an opt-in local Compose profile and CI coverage.

**Architecture:** Keep PostgreSQL as the default and select SQL Server through the existing database engine setting. Remove Jewel-owned PostgreSQL-only query behavior, disable dispatcherd/cache broadcast for SQL Server's single-node mode, and add SQL Server to the local and CI test environments.

**Tech Stack:** Django, django-ansible-base `ansible_base.backends.mssql`, mssql-django, pyodbc, Microsoft ODBC Driver 18, SQL Server 2025 Developer container, tox, GitHub Actions, Podman Compose.

**Spec:** `docs/superpowers/specs/2026-10-27-sqlserver-support-design.md`

## Global Constraints

- Use DAB's `ansible_base.backends.mssql` backend and its SQL Server compatibility helpers.
- Do not change Jewel's DAB requirement; use the existing local `django-ansible-base/` checkout and add a `Requires` line for the DAB PR to the Jewel PR description.
- Do not change Gateway models or migration files.
- Use Microsoft's SQL Server 2025 Developer image for local development and CI.
- Use ODBC Driver 18 in Gateway runtime, development, and CI images; certificate trust bypass is limited to local development and tests.
- Keep SQL Server queries below its 2100-parameter limit.
- Keep `mssql_enabled` false by default and retain PostgreSQL for the default Gateway and optional development services.
- SQL Server support is single-node for now; do not configure dispatcherd or DAB distributed cache invalidation for SQL Server.

## Review Focus

- **MSSQL settings override PostgreSQL options:** prove the JSON `DATABASE_OPTIONS` env value replaces the default `application_name`, while unset options preserve the PostgreSQL default. Task 1.
- **Health and gRPC settings contain PostgreSQL-only options:** prove the SQL Server healthcheck uses `connection_timeout` and the gRPC loader skips PG keepalive defaults. Task 1.
- **Duplicate Envoy resource names:** prove SQL Server mode selects one deterministic row per resource name. Task 2.
- **Encrypted JSON and paginated secret rotation:** prove ORM-based rotation updates JSONField and text values over multiple keyset pages on SQL Server. Task 2.
- **Large and conflicting role-assignment batches:** prove SQL Server role migration chunks disjunctions below 2100 parameters, inserts idempotently with bounded SQL, and retains DAB's helper on PostgreSQL. Task 3.
- **Single-node and SQL test-runtime behavior:** prove SQL Server startup does not configure or start the PostgreSQL broker, does not publish cache broadcasts, and the test service waits for actual readiness within a bounded timeout. Tasks 4 and 6.

---

### Task 1: Configure the DAB SQL Server backend

**Files:**
- Modify: `aap_gateway_api/settings_utils.py`
- Test: `aap_gateway_api/tests/test_settings_utils.py`

**Interfaces:**
- Consumes the existing `DATABASE_ENGINE`, `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_HOST`, and `DATABASE_PORT` environment settings.
- Adds `DATABASE_OPTIONS` as a JSON object environment value mapped to `DATABASES.default.OPTIONS`.
- Keeps the PostgreSQL engine and its current default options when SQL Server settings are absent.

- [x] Add `test_load_custom_envvars_database_options`, asserting a JSON `DATABASE_OPTIONS` value replaces the default `application_name`, and asserting unset `DATABASE_OPTIONS` preserves it; add `test_load_healthcheck_settings_uses_connection_timeout_for_mssql`, asserting `connection_timeout == 3` and no `connect_timeout`, plus `test_load_healthcheck_settings_keeps_connect_timeout_for_postgres`; add `test_load_grpc_settings_skips_postgres_defaults_for_mssql`, asserting PostgreSQL keepalives are not injected. Run these focused tests and verify the new MSSQL assertions fail.
- [x] Map `DATABASE_OPTIONS` through `load_custom_envvars` as a JSON object, replacing the default `OPTIONS` dictionary when explicitly set.
- [x] Select `connection_timeout=3` for SQL Server healthcheck settings and retain `connect_timeout=3` for PostgreSQL.
- [x] Skip loading `grpc_defaults.py` when the configured engine is `ansible_base.backends.mssql`; continue loading explicit Gateway gRPC settings.
- [x] Run `GATEWAY_TEST_DIRS="" tox -e py312 -- aap_gateway_api/tests/test_settings_utils.py -v` and confirm all settings tests pass.

### Task 2: Remove PostgreSQL-only Envoy and secret-rotation queries

**Files:**
- Modify: `aap_gateway_api/views/api/envoy/rest_control_plane.py`
- Modify: `aap_gateway_api/management/commands/rotate_secret_key.py`
- Modify: `aap_gateway_api/tests/views/api/envoy/test_rest_control_plane.py`
- Modify: `aap_gateway_api/tests/management/test_rotate_secret_key.py`

**Interfaces:**
- Keeps `XDSView.get_qs(request, model_class, name_field)` returning model instances, one per distinct `name_field`.
- Keeps secret-rotation behavior and keyset pagination, while using Django queryset slicing and updates for database-specific SQL adaptation.

- [x] Add `test_get_qs_returns_one_deterministic_row_per_name_on_mssql`, asserting two same-name rows produce the row with the lower primary key; add `test_rotate_secret_key_uses_orm_pagination_and_json_updates`, asserting keyset pages rotate both a JSONField string and a text value. Run these tests and verify the MSSQL query path or current PostgreSQL-only SQL fails.
- [x] Use `Window(RowNumber(), partition_by=F(name_field), order_by=F("pk"))` for SQL Server and preserve PostgreSQL `distinct(name_field)` behavior.
- [x] Replace raw `LIMIT` SELECTs with `order_by(pk).values_list(... )[:_FETCH_BATCH_SIZE]` keyset querysets and replace raw UPDATE statements with queryset `.update()` calls.
- [x] Remove PostgreSQL `::jsonb` writes and serialize JSONField values through Django's field preparation.
- [x] Replace PostgreSQL-only `ON CONFLICT` and `::jsonb` SQL in rotation tests with ORM operations.
- [x] Run the focused Envoy and rotation tests through `tox` on PostgreSQL and confirm they pass.

### Task 3: Make role-assignment migration safe for SQL Server

**Files:**
- Modify: `aap_gateway_api/management/commands/_migrate_service_data/role_assignments.py`
- Modify: `aap_gateway_api/management/commands/_migrate_service_data/cursor_store.py`
- Modify: `aap_gateway_api/tests/management/commands/_migrate_service_data/test_role_assignments.py`

**Interfaces:**
- Uses DAB's `bulk_create_db_safe(model_class, objects, ignore_conflicts=True)` on PostgreSQL and batched `MERGE ... WITH (HOLDLOCK)` inserts on SQL Server.
- Adds `_get_object_role_map(unique_keys)` to load `ObjectRole` rows in disjunction batches of at most 500 keys and return a map keyed by `(role_definition_id, content_type_id, object_id)`.
- Uses SQL Server-compatible `OBJECT_ID` table creation and `MERGE ... WITH (HOLDLOCK)` cursor upsert SQL when `connection.vendor == "microsoft"`; PostgreSQL keeps its existing `CREATE TABLE IF NOT EXISTS` and `ON CONFLICT` statements.

- [x] Add `test_bulk_create_db_safe_ignores_conflicts`, `test_object_role_lookup_chunks_more_than_700_keys`, and `test_cursor_store_persists_progress_on_sql_server`; assert duplicate rows are ignored, object-role keys are queried in batches of at most 500, and cursor progress persists across instances. Verify each test fails on SQL Server before its fix.
- [x] Route conflict-tolerant inserts through a backend-aware helper: use DAB's helper on PostgreSQL and SQL Server `MERGE ... WITH (HOLDLOCK)` batches on MSSQL, avoiding per-row insert fallback.
- [x] Move the object-role `Q` construction and lookup into `_get_object_role_map(unique_keys)` and query batches of at most 500 keys.
- [x] Add SQL Server table-creation and cursor upsert statements in `cursor_store.py`, selected by `connection.vendor`; preserve PostgreSQL SQL.
- [x] Run the role-assignment migration tests through `tox` on PostgreSQL and confirm they pass.

### Task 4: Disable dispatcherd and cache broadcast for SQL Server

**Files:**
- Modify: `aap_gateway_api/apps.py`
- Modify: `aap_gateway_api/dispatch/config.py`
- Modify: `aap_gateway_api/management/commands/dispatcherd.py`
- Modify: `aap_gateway_api/management/commands/dispatcherctl.py`
- Modify: `tools/configs/supervisord.conf`
- Modify: `tools/scripts/launch-gateway`
- Modify: `aap_gateway_api/settings.py`
- Test: `aap_gateway_api/tests/dispatch/test_config.py`
- Test: `aap_gateway_api/tests/dispatch/test_management_commands.py`
- Test: `aap_gateway_api/tests/test_settings_utils.py`

**Interfaces:**
- `get_dispatcherd_config()` returns `None` when the default database engine is SQL Server and returns the existing PostgreSQL config otherwise.
- The `dispatcherd` command exits cleanly when configuration is disabled.
- `launch-gateway` exports `DISPATCHERD_AUTOSTART=false` for SQL Server and true for PostgreSQL; supervisord consumes that value.

- [x] Add `test_config_is_disabled_for_mssql`, asserting `get_dispatcherd_config() is None`; add `test_dispatcherd_command_skips_service_when_disabled`, asserting `run_dispatcherd_service` is not called; add `test_dispatcherctl_reports_disabled_for_mssql`, asserting a clear `CommandError`; add `test_mssql_settings_disable_cache_auto_invalidation`, asserting the setting is false. Verify these tests fail before the change.
- [x] Skip `dispatcherd_setup()` in `MyAppConfig.ready()` when `get_dispatcherd_config()` returns `None`.
- [x] Make the management command return successfully without setting up or running dispatcherd when disabled; make `dispatcherctl` report the disabled state cleanly.
- [x] Set `ANSIBLE_BASE_REDIS_AUTO_INVALIDATE=False` after final environment settings are loaded when the engine is SQL Server.
- [x] Set the supervisord dispatcher autostart value from `launch-gateway` based on the resolved Django database engine.
- [x] Run dispatch tests on PostgreSQL and SQL Server and confirm the PostgreSQL broker remains unchanged while the SQL Server process does not start.

### Task 5: Add SQL Server to Gateway images and local Compose

**Files:**
- Modify: `tools/ansible/roles/sources/templates/Containerfile.j2`
- Modify: `tools/ansible/roles/sources/templates/compose.yml.j2`
- Modify: `tools/ansible/vars/container_config.yml`
- Modify: `tools/configs/container-startup.yml`
- Create: `tools/scripts/launch-mssql`
- Create: `tools/scripts/check-mssql`
- Modify: `CONTRIBUTING.md`

**Interfaces:**
- `mssql_enabled` defaults to false; when true, Gateway uses the `mssql` Compose service, `ansible_base.backends.mssql`, database `gateway`, and ODBC Driver 18 options.
- SQL Server uses `MSSQL_SA_PASSWORD`, `MSSQL_PID=Developer`, a persisted data volume, and a readiness check that waits for the `gateway` database.
- PostgreSQL remains available for optional local services and remains Gateway's database when `mssql_enabled` is false.

- [x] Add `mssql_enabled` and configurable SQL Server image, password, host port, and memory limit to `container-startup.yml`; verify the default remains PostgreSQL.
- [x] Add SQL Server ODBC driver and unixODBC packages to builder and runtime profiles and the CI profile in the generated Containerfile.
- [x] Render Gateway's database service, engine, credentials, port, and JSON `DATABASE_OPTIONS` from `container_config.yml` based on `mssql_enabled`.
- [x] Add the SQL Server Compose service, readiness/initialization scripts, data volume, and conditional Gateway dependency.
- [x] Document the opt-in SQL Server local workflow and its development-only certificate settings.
- [x] Generate Compose sources with SQL Server both disabled and enabled; validate both outputs with the Compose config parser and start the SQL Server profile to verify Gateway readiness.

### Task 6: Add SQL Server tox targets and CI coverage

**Files:**
- Create: `aap_gateway_api/tests/mssql_settings.py`
- Modify: `pyproject.toml`
- Modify: `.github/workflows/unit-tests.yml`
- Modify: `aap_gateway_api/tests/service_test_app/launch.py`
- Test: `aap_gateway_api/tests/test_service_test_app_launch.py`

**Interfaces:**
- Adds `tox -e py312-mssql` for the Gateway unit suite and `tox -e py312-mssql-check` for Django checks and migration validation.
- Uses `ANSIBLE_GW_TEST_DB_HOST`, `DB_PORT`, and a SQL Server settings module with `ansible_base.backends.mssql`, ODBC Driver 18, and development-only certificate trust.
- Adds a `unit-test-mssql` CI job using SQL Server 2025 Developer and the existing Jewel CI image. The Jewel PR description must include a `Requires` line for the DAB PR so the existing dependency checkout step uses the SQL Server backend checkout.

- [x] Add `mssql_settings.py` with the SQL Server database contract and the tox SQL Server service. Verify environment setup and reach SQL Server with focused database tests.
- [x] Add `py312-mssql` and `py312-mssql-check` tox environments and include them in the `mssql` label.
- [x] Add the SQL Server service container and `unit-test-mssql` CI job. Install ODBC Driver 18 in the job before testing because the workflow uses the base-branch CI image; set four pytest workers and upload SQL Server JUnit results.
- [x] Set `PYTEST_NUM_PROCESSES=4` by default for the SQL Server tox target and CI job, while allowing local override.
- [x] Add `test_launch_service_waits_for_delayed_readiness`, simulating a service that responds after 21 poll attempts; verify the current 10-second startup loop fails. Add `test_launch_service_captures_child_logs_without_pipe_blocking`, asserting captured child output uses a non-pipe sink. Update the launcher to poll readiness for up to 60 seconds, detect early child exit, and capture stdout/stderr in temporary files so the child cannot block on full pipes; route service-fixture teardown through `stop_service()` so the files close promptly.
- [x] Record the required PR description line `Requires ansible/django-ansible-base#<DAB-PR-number>` before CI is expected to check out the SQL Server backend.
- [x] Run `tox -e py312-mssql-check` and the full `tox -e py312-mssql` suite against SQL Server; 2,451 passed, 13 skipped, 10 xfailed, and 3 xpassed.
- [x] Run the existing PostgreSQL unit suite and the existing lint target; 2,462 passed, 2 skipped, 10 xfailed, and 3 xpassed, with lint passing.

