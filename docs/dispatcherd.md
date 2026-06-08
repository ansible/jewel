# Dispatcherd Integration in Gateway

Epic: [AAP-59888](https://redhat.atlassian.net/browse/AAP-59888)

> **This document is a living specification.** It serves as the single source of truth for the dispatcherd integration work. Multiple contributors (each using Claude Code) will work on different stories — read this doc into context before starting any work, and update the relevant sections when your work is complete. Keep descriptions precise; other sessions will rely on them to understand what exists, what the constraints are, and what is left to do.

## How to Use This Document

1. **Before starting work**: Read this entire doc. Check the [Current State](#current-state) section and the [Progress Tracker](#progress-tracker) to understand what has been completed.
2. **While working**: Follow the specifications in the relevant section. Do not deviate from stated interfaces, file paths, naming, or behavioral contracts without updating this doc first.
3. **After completing work**: Update the relevant section — replace `<!-- TODO -->` markers with actual details (file paths created, config keys used, example output, etc.). Update the [Current State](#current-state) summary and mark your story as complete in the [Progress Tracker](#progress-tracker).

## Current State

<!-- Update this section after each story is completed so the next person gets a quick snapshot. -->

**Last updated**: 2026-05-06

AAP-65393 (core implementation) is complete and merged. The dispatch module, management commands, settings defaults, app config wiring, logging config, and unit tests are all in place.

AAP-65394 (supervisord config) is code-complete. The dispatcher program block has been added to supervisord.conf and the podman startup config has been updated with gateway status endpoint preferences.

---

## Overview

Gateway integrates [dispatcherd](https://github.com/ansible/dispatcherd) to provide background task processing via PostgreSQL `pg_notify`. The primary motivation is to support cache invalidation across a Gateway cluster as part of the sidecar Redis tech preview (ANSTRAT-1568), though dispatcherd can be used to schedule any background task within the system.

## Architecture

<!-- TODO: Add diagram showing Gateway <-> dispatcherd <-> PostgreSQL relationship -->

dispatcherd runs as a separate process alongside the Gateway web server. It listens on PostgreSQL notification channels and dispatches work to registered task handlers. Each Gateway node in a cluster runs its own dispatcherd instance, identified by the node's `CLUSTER_HOST_ID` Django setting. A broadcast queue allows messages to reach all nodes simultaneously.

### Component Layout

```
aap_gateway_api/
├── dispatch/                    # dispatcherd integration module
│   ├── config.py                # dispatcherd configuration (node name, queues)
│   └── ...
├── management/commands/
│   ├── dispatcherd.py           # Management command to run the service
│   └── dispatcherctl.py         # Management command for control operations
└── tests/dispatch/              # Unit tests for dispatch module
```

### Key Dependencies

| Dependency | Source | Purpose |
| --- | --- | --- |
| `dispatcherd` | [PyPI](https://pypi.org/project/dispatcherd/) | Background task processing via pg_notify |
| `psycopg` | [PyPI](https://pypi.org/project/psycopg/) | PostgreSQL adapter (v3.x) — requires ≥3.2.10 for same-connection notification support |
| `psycopg_conn_string_from_settings_dict()` | `ansible_base.lib.utils.db` (DAB) | Build a properly-escaped conninfo string from Django's DB config |
| `psycopg_connection_from_django()` | `ansible_base.lib.utils.db` (DAB) | Obtain a raw psycopg connection from Django's DB config |

### Logging

A `dispatcherd` logger is configured in `aap_gateway_api/defaults.py` at WARNING level by default. Set to DEBUG for troubleshooting:

```python
LOGGING['loggers']['dispatcherd']['level'] = 'DEBUG'
```

Without this logger, all dispatcherd internal log output is silently dropped (discovered during initial dev testing — EDA has the same logger configured).

### References

- [dispatcherd README](https://github.com/ansible/dispatcherd/blob/main/README.md)
- [dispatcherd configuration docs](https://github.com/ansible/dispatcherd/blob/main/docs/config.md)
- EDA's implementation can be used as a reference for management commands

---

## Specifications by Story

### AAP-65393: Implement dispatcherd in Gateway

**Story**: [AAP-65393](https://redhat.atlassian.net/browse/AAP-65393) | **Status**: Complete

This is the foundational story. All other stories depend on it.

#### Requirements

| Item | Specification |
| --- | --- |
| Dependency | Add `dispatcherd[pg_notify]` to `requirements/requirements.in` |
| Module location | `aap_gateway_api/dispatch/` |
| Config | `config.py` — use `CLUSTER_HOST_ID` (Django setting) for the node name. Configure a broadcast queue. Config dict is passed to dispatcherd's `run_service()`. |
| Management commands | `aap_gateway_api/management/commands/dispatcherd.py` and `dispatcherctl.py` |
| Unit tests | `aap_gateway_api/tests/dispatch/` — cover config module and management commands |
| DB connection | Use DAB's `psycopg_conn_string_from_settings_dict()` for conninfo and `psycopg_connection_from_django` as the sync connection factory, both from `ansible_base.lib.utils.db` |

#### Constraints

- Do **not** create a custom `GatewayTaskWorker` subclass — use dispatcherd's built-in `TaskWorker` directly.
- Keep the initial configuration minimal: enough for dispatcherd to start, listen, and process tasks.

#### Files Created / Modified

- Created: `aap_gateway_api/dispatch/__init__.py`
- Created: `aap_gateway_api/dispatch/config.py` — `get_dispatcherd_config()`
- Created: `aap_gateway_api/dispatch/pre_fork.py` — pre-fork Django setup (closes DB/cache connections before fork)
- Created: `aap_gateway_api/management/commands/dispatcherd.py` — runs the service
- Created: `aap_gateway_api/management/commands/dispatcherctl.py` — control interface (alive, status, etc.)
- Created: `aap_gateway_api/tests/dispatch/__init__.py`
- Created: `aap_gateway_api/tests/dispatch/test_config.py`
- Created: `aap_gateway_api/tests/dispatch/test_management_commands.py`
- Modified: `requirements/requirements.in` — added `dispatcherd[pg_notify]`
- Modified: `requirements/requirements.txt` — compiled; pins dispatcherd and psycopg ≥3.2.10
- Modified: `aap_gateway_api/defaults.py` — added `DISPATCHERD_MIN_WORKERS`, `DISPATCHERD_MAX_WORKERS`, and `dispatcherd` logger
- Modified: `aap_gateway_api/apps.py` — calls `dispatcherd_setup(get_dispatcherd_config())` in `ready()`

#### Configuration Details

The config dict passed to `dispatcherd.config.setup()` and `run_service()`:

```python
{
    "version": 2,
    "service": {
        "process_manager_cls": "ForkServerManager",
        "process_manager_kwargs": {
            "preload_modules": ["aap_gateway_api.dispatch.pre_fork"],
        },
        "min_workers": 2,   # from settings.DISPATCHERD_MIN_WORKERS
        "max_workers": 4,   # from settings.DISPATCHERD_MAX_WORKERS
    },
    "brokers": {
        "pg_notify": {
            "config": {
                "conninfo": "<built from DATABASES['default']>",
            },
            "sync_connection_factory": "ansible_base.lib.utils.db.psycopg_connection_from_django",
            "channels": [
                "<CLUSTER_HOST_ID>",   # node-specific channel
                "gateway_broadcast",   # cluster-wide broadcast channel
            ],
            "default_publish_channel": "gateway_broadcast",
        }
    },
    "producers": {},
    "publish": {"default_broker": "pg_notify"},
}
```

The `conninfo` string is built from `settings.DATABASES["default"]` using DAB's `psycopg_conn_string_from_settings_dict()` from `ansible_base.lib.utils.db`, which delegates to `psycopg.conninfo.make_conninfo()` for proper escaping of special characters in passwords and other values. The `sync_connection_factory` points to DAB's `psycopg_connection_from_django` which reuses Django's existing DB connection.

---

### AAP-65394: Add dispatcherd to supervisord configuration

**Story**: [AAP-65394](https://redhat.atlassian.net/browse/AAP-65394) | **Status**: In Review
**Depends on**: AAP-65393

#### Requirements

| Item | Specification |
| --- | --- |
| Config file | `tools/configs/supervisord.conf` |
| Program block | `[program:dispatcher]` |
| Command | `/usr/bin/aap-gateway-manage dispatcherd` |
| Group | Add `dispatcher` to the `gateway-processes` group |
| `autorestart` | `true` |
| `stopasgroup` | `true` |
| `killasgroup` | `true` |

#### Constraints

- `stopasgroup` and `killasgroup` must be `true`. Each supervisord program gets its own OS process group (PGID), so the signal only reaches the dispatcher's process tree — not nginx, uwsgi, or other gateway processes. Without this, the bash wrapper (`aap-gateway-manage`) absorbs SIGTERM and the Python dispatcherd process is never signaled, leaving orphaned processes on every restart.

#### Files Modified

- Modified: `tools/configs/supervisord.conf` — added `[program:dispatcher]` block; added `dispatcher` to `gateway-processes` group
- Modified: `tools/configs/container-startup-podman.yml` — added `gateway_preferences` for status endpoint timeout and TLS verify settings

---

### AAP-65395: Add dispatcherd health check to ping endpoint

**Story**: [AAP-65395](https://redhat.atlassian.net/browse/AAP-65395) | **Status**: Backlog
**Depends on**: AAP-65393

#### Requirements

| Item | Specification |
| --- | --- |
| File to modify | `aap_gateway_api/views/api/v1/ping.py` |
| Health check method | `dispatcherctl.alive()` |
| Response field | `dispatcherd_connected` (boolean) |
| Status impact | Does **not** set `STATUS_DEGRADED` — overall status remains `good` even if dispatcherd is unavailable |
| Unit tests | Add tests for the new field in the ping endpoint |
| ATF tests | Verify `dispatcherd_connected` field in ping/status; verify no degradation when `false` |
| ATF process manager | Add stop/start support for dispatcherd |

#### Constraints

- The `dispatcherd_connected` field is purely informational. It must **never** cause the overall ping status to degrade.

#### Example Response

<!-- TODO: Add actual ping response JSON showing dispatcherd_connected once implemented.
     Expected shape:
     ```json
     {
       ...
       "dispatcherd_connected": true,
       ...
     }
     ```
-->

---

### AAP-65396: Update Gateway container build

**Story**: [AAP-65396](https://redhat.atlassian.net/browse/AAP-65396) | **Status**: Backlog
**Depends on**: AAP-65393

**Repository**: [automation-gateway-container](https://github.com/ansible/automation-gateway-container)

#### Requirements

1. Update the `aap-gateway` submodule to include the dispatcherd dependency
2. Regenerate `requirements.txt` (see comment at top of file for the command)
3. Regenerate `requirements-build.txt` using `pybuild-deps`
4. Submit PR and verify the Konflux pipeline passes

#### Constraints

- Konflux requires locked, hashed dependencies for supply chain security — do not manually edit requirements files.
- The regeneration commands are documented in comments at the top of each requirements file.

---

### AAP-65397: Baseline performance test

**Story**: [AAP-65397](https://redhat.atlassian.net/browse/AAP-65397) | **Status**: Backlog
**Depends on**: AAP-65396

#### Data Sources

- **Jenkins pipeline**: [tier2-cont-b.fresh-install.performance](https://jenkins-csb-aap-main.dno.corp.redhat.com/job/AAPQA/job/AAP_2.8_Next/job/Product_Build_CI/view/CONT/job/tier2-cont-b.fresh-install.performance/) — triggers the performance test runs against `cont-b` topology.
- **Performance dashboard** (API benchmark): [aap-perf-dashboard](https://aap-perf-dashboard-perfscale-aap-dashboard.apps.ocp4.intlab.redhat.com/data/api_benchmark.html) — aggregated results with trend data. Filter to **version 2.8** / **gateway** / **cont-b**.
- **Raw result documents**: Available via the dashboard's Elasticsearch API:
  ```
  https://aap-perf-dashboard-perfscale-aap-dashboard.apps.ocp4.intlab.redhat.com/api/es-doc?index=atf_test_api_benchmark&id=<doc_id>
  ```
  The `<doc_id>` is visible in the dashboard UI when expanding a run's details.

#### What the Benchmark Measures

The test suite (`tests/perf/benchmark/test_api_benchmark.py`) exercises controller API endpoints **routed through the gateway**. There are three test functions:

| Test Function | What It Tests |
| --- | --- |
| `test_benchmark_controller_endpoint_list_response` | List (GET collection) endpoints |
| `test_benchmark_controller_endpoint_get_response` | Detail (GET single resource) endpoints |
| `test_benchmark_controller_endpoint_create_response` | Create (POST) endpoints |

Each endpoint is tested across four credential/auth types: `basic`, `session`, `token`, `org-admin-session`. Each combination is hit for multiple rounds. The raw results store these per-endpoint stats:

| Stat | Description |
| --- | --- |
| `mean` | Average response time (seconds) |
| `max` | Worst-case response time |
| `min` | Best-case response time |
| `median` | 50th percentile |
| `stddev` | Standard deviation |
| `rounds` | Number of requests made |
| `ops` | Throughput (requests/sec) |
| `q1` / `q3` / `iqr` | Quartile stats |

SLO thresholds (P50 ≤ 500ms, P99 ≤ 1500ms) are computed by the dashboard layer, not stored in the raw results.

In addition to endpoint latencies, the benchmark captures **per-component resource utilization** (under `automation_gateway` in the raw JSON):

| Resource | Sub-metrics (each has max, median, stddev, p99) |
| --- | --- |
| CPU | `avg_across_cores`, `max_core`, `min_core`, `system_percent`, `user_percent`, `idle_percent`, `iowait_percent` |
| Memory | `total`, `free` (max/median), `used` (max/median) |
| Disk | `total`, `reads`, `writes` |
| Network | `total`, `inbound`, `outbound`, `errors`, `drops` |

#### Exactly What to Collect for Comparison

To ensure an apples-to-apples comparison between pre- and post-dispatcherd runs, collect **all** of the following from the raw Elasticsearch document:

**1. Run metadata** (top-level fields):
- `started` / `ended` timestamps
- `nvr` (build identifier)
- Topology and installation type (should be `cont-b` / `containerized`)

**2. Gateway resource utilization** — from the `automation_gateway` section of the raw JSON, record max and median for:
- CPU avg across cores
- CPU max core
- CPU user% avg
- CPU system% avg
- CPU iowait% avg
- Memory used
- Disk writes
- Network inbound + outbound

**3. Endpoint latencies** — from the `results` array, record `mean`, `median`, `max`, `rounds`, and `ops` for every `*-basic` auth endpoint. The basic auth type is the primary comparison axis since it exercises the same code path consistently. The full list of endpoints tested with basic auth is:

> credentials, credential_types, groups, host, instances, instance_groups, inventories, inventory_sources, inventory_updates, jobs, job_templates, me, notifications, notification_templates, organizations, projects, roles, schedules, teams, users, workflow_jobs, workflow_job_nodes, workflow_job_templates, workflow_job_template_nodes, settings, credential (create), credential_type (create)

If any endpoint shows a notable change, expand the comparison to its other auth types (session, token, org-admin-session) to confirm whether the regression is auth-specific or systemic.

#### Pre-dispatcherd Baseline (2026-04-29)

Source: [raw result doc xgsC2Z0BROvgJxmV6QHd](https://aap-perf-dashboard-perfscale-aap-dashboard.apps.ocp4.intlab.redhat.com/api/es-doc?index=atf_test_api_benchmark&id=xgsC2Z0BROvgJxmV6QHd)
NVR: `ansible-automation-platform-next-2.8-20260429.aap-devel-20260428-225751-000`
Topology: `cont-b` | Installation: `containerized`
Run window: 2026-04-29 09:22 – 10:10 UTC

**Gateway resource utilization:**

| Metric | Max | Median | Stddev | P99 |
| --- | --- | --- | --- | --- |
| CPU avg across cores | 15.16% | 9.82% | 3.72% | 14.89% |
| CPU max core | 34.71% | 17.71% | 8.86% | 34.10% |
| CPU user% avg | 11.34% | 6.87% | 3.14% | 11.23% |
| CPU system% avg | 2.75% | 2.04% | 0.49% | 2.68% |
| CPU iowait% avg | 0.012% | 0.003% | 0.003% | 0.011% |
| Memory used | 31,725,388 B | 29,429,616 B | — | — |
| Memory free | 66,958,720 B | 65,465,748 B | — | — |
| Disk writes | 409,965 MB | 400,444 MB | — | — |
| Network inbound | 8,862,321 B | 6,800,582 B | — | — |
| Network outbound | 7,718,614 B | 5,359,737 B | — | — |

**Controller endpoint latencies (proxied through gateway) — list responses, basic auth (seconds):**

| Endpoint | Mean | Median | Min | Max | Stddev | Rounds | Ops/s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| credentials | 0.18 | 0.18 | 0.17 | 0.19 | 0.01 | 28 | 5.81 |
| credential_types | 0.16 | 0.16 | 0.16 | 0.18 | 0.01 | 32 | 6.28 |
| groups | 0.15 | 0.14 | 0.14 | 0.16 | 0.01 | 36 | 7.08 |
| host | 0.27 | 0.26 | 0.25 | 0.43 | 0.04 | 21 | 3.76 |
| instances | 0.18 | 0.18 | 0.17 | 0.30 | 0.03 | 28 | 5.56 |
| instance_groups | 0.16 | 0.16 | 0.16 | 0.17 | 0.01 | 32 | 6.33 |
| inventories | 0.17 | 0.17 | 0.17 | 0.19 | 0.01 | 30 | 5.99 |
| inventory_sources | 0.15 | 0.15 | 0.15 | 0.16 | 0.01 | 36 | 6.92 |
| inventory_updates | 0.15 | 0.15 | 0.15 | 0.16 | 0.01 | 34 | 6.87 |
| jobs | 0.16 | 0.15 | 0.15 | 0.27 | 0.03 | 35 | 6.63 |
| job_templates | 0.19 | 0.19 | 0.18 | 0.34 | 0.03 | 28 | 5.37 |
| me | 0.15 | 0.15 | 0.15 | 0.16 | 0.01 | 34 | 6.81 |
| notifications | 0.15 | 0.15 | 0.14 | 0.17 | 0.01 | 35 | 6.78 |
| notification_templates | 0.14 | 0.14 | 0.14 | 0.15 | 0.01 | 34 | 7.18 |
| organizations | 0.17 | 0.17 | 0.17 | 0.19 | 0.01 | 30 | 5.93 |
| projects | 0.18 | 0.18 | 0.18 | 0.21 | 0.01 | 29 | 5.63 |
| roles | 0.19 | 0.19 | 0.18 | 0.21 | 0.01 | 28 | 5.44 |
| schedules | 0.16 | 0.16 | 0.16 | 0.17 | 0.01 | 32 | 6.48 |
| teams | 0.17 | 0.16 | 0.16 | 0.18 | 0.01 | 32 | 6.20 |
| users | 0.19 | 0.19 | 0.19 | 0.20 | 0.01 | 28 | 5.34 |
| workflow_jobs | 0.15 | 0.15 | 0.14 | 0.16 | 0.01 | 35 | 6.96 |
| workflow_job_nodes | 0.15 | 0.15 | 0.14 | 0.16 | 0.01 | 36 | 7.04 |
| workflow_job_templates | 0.20 | 0.20 | 0.20 | 0.22 | 0.01 | 26 | 5.04 |
| workflow_job_template_nodes | 0.15 | 0.15 | 0.14 | 0.16 | 0.01 | 36 | 7.07 |

**Controller endpoint latencies — get/create responses, basic auth (seconds):**

| Test Type | Endpoint | Mean | Median | Min | Max | Stddev | Rounds | Ops/s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| get | settings | 0.15 | 0.15 | 0.14 | 0.16 | 0.01 | 36 | 7.02 |
| create | credential | 0.18 | 0.18 | 0.17 | 0.19 | 0.01 | 29 | 5.76 |
| create | credential_type | 0.15 | 0.15 | 0.15 | 0.16 | 0.01 | 35 | 6.77 |
| create | execution_environment | 0.16 | 0.16 | 0.16 | 0.19 | 0.01 | 30 | 6.48 |
| create | group | 0.16 | 0.16 | 0.15 | 0.17 | 0.01 | 33 | 6.45 |
| create | inventory | 0.18 | 0.18 | 0.17 | 0.19 | 0.01 | 30 | 5.85 |
| create | instance_group | 0.17 | 0.17 | 0.17 | 0.18 | 0.01 | 29 | 6.04 |
| create | inventory_source | 0.20 | 0.20 | 0.19 | 0.22 | 0.01 | 26 | 5.21 |
| create | job | 0.26 | 0.26 | 0.25 | 0.30 | 0.02 | 21 | 3.86 |
| create | job_template | 0.19 | 0.18 | 0.18 | 0.20 | 0.01 | 29 | 5.56 |
| create | notification_template | 0.17 | 0.17 | 0.16 | 0.18 | 0.01 | 29 | 6.08 |
| create | workflow_job_template | 0.18 | 0.17 | 0.17 | 0.19 | 0.01 | 30 | 5.84 |
| create | project0 | 0.35 | 0.33 | 0.20 | 0.55 | 0.12 | 27 | 2.91 |
| create | workflow_job_template_node | 0.17 | 0.16 | 0.16 | 0.18 | 0.01 | 31 | 6.25 |
| create | project1 | 0.35 | 0.35 | 0.21 | 0.58 | 0.11 | 27 | 2.88 |

**Gateway-native endpoint latencies — list responses, basic auth (seconds):**

| Endpoint | Mean | Median | Min | Max | Stddev | Rounds | Ops/s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| application | 0.14 | 0.14 | 0.13 | 0.16 | 0.01 | 36 | 7.33 |
| authenticator | 0.13 | 0.13 | 0.13 | 0.15 | 0.01 | 41 | 7.85 |
| authenticator_maps | 0.13 | 0.13 | 0.12 | 0.14 | 0.01 | 41 | 8.22 |
| organization | 0.16 | 0.16 | 0.15 | 0.18 | 0.01 | 35 | 6.63 |
| role_definition | 0.16 | 0.16 | 0.15 | 0.23 | 0.02 | 33 | 6.29 |
| role_team_assignment | 0.13 | 0.13 | 0.12 | 0.15 | 0.01 | 41 | 8.10 |
| role_user_assignment | 0.14 | 0.13 | 0.13 | 0.15 | 0.01 | 39 | 7.60 |
| service_cluster | 0.15 | 0.15 | 0.14 | 0.15 | 0.01 | 35 | 7.02 |
| setting | 0.13 | 0.13 | 0.12 | 0.14 | 0.01 | 42 | 8.18 |
| team | 0.18 | 0.18 | 0.17 | 0.20 | 0.01 | 29 | 5.75 |
| tokens | 0.14 | 0.14 | 0.14 | 0.16 | 0.01 | 37 | 7.34 |
| user | 0.37 | 0.38 | 0.35 | 0.39 | 0.02 | 15 | 2.71 |

**Gateway-native endpoint latencies — create responses, basic auth (seconds):**

| Test Type | Endpoint | Mean | Median | Min | Max | Stddev | Rounds | Ops/s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| create | organization | 0.27 | 0.27 | 0.25 | 0.29 | 0.02 | 20 | 3.81 |
| create | user | 0.36 | 0.34 | 0.33 | 0.49 | 0.05 | 14 | 2.86 |
| create | team | 0.31 | 0.30 | 0.29 | 0.33 | 0.01 | 17 | 3.32 |

#### How to Collect Post-dispatcherd Results

1. Wait for a successful `tier2-cont-b.fresh-install.performance` Jenkins run after the dispatcherd container build (AAP-65396) has shipped.
2. Open the [performance dashboard](https://aap-perf-dashboard-perfscale-aap-dashboard.apps.ocp4.intlab.redhat.com/data/api_benchmark.html) and filter to **version 2.8** / **gateway** / **cont-b**.
3. Expand the run to find its Elasticsearch doc ID, then fetch the raw JSON:
   ```
   https://aap-perf-dashboard-perfscale-aap-dashboard.apps.ocp4.intlab.redhat.com/api/es-doc?index=atf_test_api_benchmark&id=<doc_id>
   ```
4. From the raw JSON, extract:
   - Run metadata: `started`, `ended`, `nvr`
   - `automation_gateway` resource utilization (CPU, memory, disk, network) — record in the same table format as the baseline
   - All `*-basic` endpoint stats from the `results` array — record in the same table format as the baseline
5. Fill in the **Post-dispatcherd Results** section below and compare against the baseline.

#### Post-dispatcherd Results

Source: `tier2-cont-b.fresh-install.performance` build 19, artifact `atf_aap_performance_test_suite/opensearch_status_data.json`
NVR: `ansible-automation-platform-next-2.8-20260515.aap-devel-20260514-223412-000`
Topology: `cont-b` | Installation: `containerized`
Run window: 2026-05-15 09:00 – 09:47 UTC

**Gateway resource utilization:**

| Metric | Max | Median | Stddev | P99 |
| --- | --- | --- | --- | --- |
| CPU avg across cores | 15.03% | 10.42% | 3.60% | 14.43% |
| CPU max core | 34.22% | 17.49% | 8.57% | 33.18% |
| CPU user% avg | 11.26% | 7.35% | 3.03% | 10.71% |
| CPU system% avg | 2.68% | 2.05% | 0.49% | 2.62% |
| CPU iowait% avg | 0.017% | 0.003% | 0.003% | 0.014% |
| Memory used | 33,115,460 B | 30,892,364 B | — | — |
| Memory free | 65,362,524 B | 64,003,000 B | — | — |
| Disk writes | 409,353 MB | 400,539 MB | — | — |
| Network inbound | 8,961,274 B | 6,918,714 B | — | — |
| Network outbound | 7,950,806 B | 5,604,325 B | — | — |

**Controller endpoint latencies (proxied through gateway) — list responses, basic auth (seconds):**

| Endpoint | Mean | Median | Min | Max | Stddev | Rounds | Ops/s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| credentials | 0.18 | 0.18 | 0.18 | 0.19 | 0.01 | 28 | 5.73 |
| credential_types | 0.17 | 0.17 | 0.16 | 0.18 | 0.01 | 32 | 6.15 |
| groups | 0.15 | 0.15 | 0.14 | 0.16 | 0.01 | 35 | 6.86 |
| host | 0.26 | 0.26 | 0.26 | 0.28 | 0.01 | 20 | 3.87 |
| instances | 0.19 | 0.18 | 0.18 | 0.19 | 0.01 | 28 | 5.56 |
| instance_groups | 0.17 | 0.17 | 0.16 | 0.18 | 0.01 | 31 | 6.18 |
| inventories | 0.17 | 0.17 | 0.17 | 0.19 | 0.01 | 30 | 5.91 |
| inventory_sources | 0.15 | 0.15 | 0.15 | 0.16 | 0.01 | 33 | 6.81 |
| inventory_updates | 0.15 | 0.15 | 0.15 | 0.16 | 0.01 | 34 | 6.74 |
| jobs | 0.15 | 0.15 | 0.15 | 0.16 | 0.01 | 34 | 6.82 |
| job_templates | 0.19 | 0.19 | 0.18 | 0.20 | 0.01 | 18 | 5.51 |
| me | 0.16 | 0.16 | 0.15 | 0.17 | 0.01 | 32 | 6.43 |
| notifications | 0.15 | 0.14 | 0.14 | 0.15 | 0.01 | 36 | 7.14 |
| notification_templates | 0.15 | 0.14 | 0.14 | 0.16 | 0.01 | 36 | 7.12 |
| organizations | 0.17 | 0.17 | 0.17 | 0.19 | 0.01 | 31 | 5.93 |
| projects | 0.18 | 0.18 | 0.18 | 0.22 | 0.02 | 27 | 5.58 |
| roles | 0.19 | 0.19 | 0.18 | 0.21 | 0.01 | 26 | 5.44 |
| schedules | 0.16 | 0.16 | 0.16 | 0.17 | 0.01 | 32 | 6.48 |
| teams | 0.16 | 0.16 | 0.16 | 0.17 | 0.01 | 32 | 6.34 |
| users | 0.19 | 0.19 | 0.19 | 0.20 | 0.01 | 28 | 5.39 |
| workflow_jobs | 0.15 | 0.15 | 0.14 | 0.16 | 0.01 | 36 | 7.01 |
| workflow_job_nodes | 0.14 | 0.14 | 0.14 | 0.15 | 0.01 | 37 | 7.19 |
| workflow_job_templates | 0.21 | 0.20 | 0.19 | 0.36 | 0.04 | 26 | 4.99 |
| workflow_job_template_nodes | 0.14 | 0.14 | 0.14 | 0.16 | 0.01 | 36 | 7.15 |

**Controller endpoint latencies — get/create responses, basic auth (seconds):**

| Test Type | Endpoint | Mean | Median | Min | Max | Stddev | Rounds | Ops/s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| get | settings | 0.14 | 0.14 | 0.14 | 0.16 | 0.01 | 17 | 7.23 |
| create | credential | 0.17 | 0.17 | 0.17 | 0.19 | 0.01 | 30 | 5.93 |
| create | credential_type | 0.15 | 0.15 | 0.15 | 0.17 | 0.01 | 35 | 6.89 |
| create | execution_environment | 0.16 | 0.16 | 0.15 | 0.17 | 0.01 | 33 | 6.63 |
| create | group | 0.16 | 0.15 | 0.15 | 0.17 | 0.01 | 33 | 6.67 |
| create | inventory | 0.17 | 0.17 | 0.16 | 0.18 | 0.01 | 28 | 6.21 |
| create | instance_group | 0.17 | 0.17 | 0.17 | 0.19 | 0.01 | 30 | 6.00 |
| create | inventory_source | 0.19 | 0.19 | 0.19 | 0.20 | 0.01 | 27 | 5.29 |
| create | job | 0.27 | 0.27 | 0.25 | 0.32 | 0.02 | 21 | 3.74 |
| create | job_template | 0.18 | 0.18 | 0.17 | 0.19 | 0.01 | 28 | 5.71 |
| create | notification_template | 0.17 | 0.17 | 0.16 | 0.19 | 0.01 | 31 | 6.15 |
| create | workflow_job_template | 0.18 | 0.17 | 0.17 | 0.18 | 0.01 | 30 | 5.88 |
| create | project0 | 0.32 | 0.33 | 0.20 | 0.45 | 0.07 | 27 | 3.17 |
| create | workflow_job_template_node | 0.16 | 0.16 | 0.16 | 0.18 | 0.01 | 32 | 6.30 |
| create | project1 | 0.31 | 0.31 | 0.19 | 0.46 | 0.07 | 26 | 3.33 |

**Gateway-native endpoint latencies — list responses, basic auth (seconds):**

| Endpoint | Mean | Median | Min | Max | Stddev | Rounds | Ops/s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| application | 0.14 | 0.14 | 0.13 | 0.15 | 0.01 | 37 | 7.48 |
| authenticator | 0.13 | 0.13 | 0.12 | 0.14 | 0.01 | 38 | 8.08 |
| authenticator_maps | 0.13 | 0.13 | 0.12 | 0.18 | 0.01 | 42 | 8.17 |
| organization | 0.16 | 0.15 | 0.15 | 0.28 | 0.03 | 34 | 6.40 |
| role_definition | 0.16 | 0.16 | 0.15 | 0.21 | 0.02 | 34 | 6.48 |
| role_team_assignment | 0.13 | 0.13 | 0.12 | 0.14 | 0.01 | 41 | 8.15 |
| role_user_assignment | 0.13 | 0.13 | 0.13 | 0.15 | 0.01 | 40 | 7.74 |
| service_cluster | 0.15 | 0.15 | 0.14 | 0.15 | 0.01 | 35 | 7.14 |
| setting | 0.12 | 0.12 | 0.12 | 0.14 | 0.01 | 42 | 8.36 |
| team | 0.18 | 0.17 | 0.17 | 0.19 | 0.01 | 29 | 5.88 |
| tokens | 0.13 | 0.13 | 0.13 | 0.15 | 0.01 | 40 | 7.74 |
| user | 0.24 | 0.24 | 0.23 | 0.25 | 0.01 | 22 | 4.32 |

**Gateway-native endpoint latencies — create responses, basic auth (seconds):**

| Test Type | Endpoint | Mean | Median | Min | Max | Stddev | Rounds | Ops/s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| create | organization | 0.28 | 0.27 | 0.25 | 0.45 | 0.05 | 20 | 3.68 |
| create | user | 0.34 | 0.35 | 0.33 | 0.37 | 0.02 | 15 | 2.95 |
| create | team | 0.30 | 0.29 | 0.29 | 0.35 | 0.02 | 18 | 3.43 |

#### Comparison: Pre- vs Post-dispatcherd

**Gateway resource utilization (median):**

| Metric | Pre | Post | Delta | Verdict |
| --- | --- | --- | --- | --- |
| CPU avg across cores | 9.82% | 10.42% | +0.60 pp | Unchanged |
| CPU max core | 17.71% | 17.49% | -0.22 pp | Unchanged |
| CPU user% avg | 6.87% | 7.35% | +0.48 pp | Unchanged |
| CPU system% avg | 2.04% | 2.05% | +0.01 pp | Unchanged |
| CPU iowait% avg | 0.003% | 0.003% | 0.000 pp | Unchanged |
| Memory used | 29,429,616 B | 30,892,364 B | +5.0% (+1.4 MB) | Minor increase |
| Network inbound | 6,800,582 B | 6,918,714 B | +1.7% | Unchanged |
| Network outbound | 5,359,737 B | 5,604,325 B | +4.6% | Unchanged |

**Controller endpoint latencies — list responses, basic auth (mean, seconds):**

| Endpoint | Pre Mean | Post Mean | Delta (ms) | Delta (%) |
| --- | --- | --- | --- | --- |
| credentials | 0.18 | 0.18 | +0 | +0.0% |
| credential_types | 0.16 | 0.17 | +10 | +6.3% |
| groups | 0.15 | 0.15 | +0 | +0.0% |
| host | 0.27 | 0.26 | -10 | -3.7% |
| instances | 0.18 | 0.19 | +10 | +5.6% |
| instance_groups | 0.16 | 0.17 | +10 | +6.3% |
| inventories | 0.17 | 0.17 | +0 | +0.0% |
| inventory_sources | 0.15 | 0.15 | +0 | +0.0% |
| inventory_updates | 0.15 | 0.15 | +0 | +0.0% |
| jobs | 0.16 | 0.15 | -10 | -6.3% |
| job_templates | 0.19 | 0.19 | +0 | +0.0% |
| me | 0.15 | 0.16 | +10 | +6.7% |
| notifications | 0.15 | 0.15 | +0 | +0.0% |
| notification_templates | 0.14 | 0.15 | +10 | +7.1% |
| organizations | 0.17 | 0.17 | +0 | +0.0% |
| projects | 0.18 | 0.18 | +0 | +0.0% |
| roles | 0.19 | 0.19 | +0 | +0.0% |
| schedules | 0.16 | 0.16 | +0 | +0.0% |
| teams | 0.17 | 0.16 | -10 | -5.9% |
| users | 0.19 | 0.19 | +0 | +0.0% |
| workflow_jobs | 0.15 | 0.15 | +0 | +0.0% |
| workflow_job_nodes | 0.15 | 0.14 | -10 | -6.7% |
| workflow_job_templates | 0.20 | 0.21 | +10 | +5.0% |
| workflow_job_template_nodes | 0.15 | 0.14 | -10 | -6.7% |

**Controller endpoint latencies — get/create responses, basic auth (mean, seconds):**

| Test Type | Endpoint | Pre Mean | Post Mean | Delta (ms) | Delta (%) |
| --- | --- | --- | --- | --- | --- |
| get | settings | 0.15 | 0.14 | -10 | -6.7% |
| create | credential | 0.18 | 0.17 | -10 | -5.6% |
| create | credential_type | 0.15 | 0.15 | +0 | +0.0% |
| create | execution_environment | 0.16 | 0.16 | +0 | +0.0% |
| create | group | 0.16 | 0.16 | +0 | +0.0% |
| create | inventory | 0.18 | 0.17 | -10 | -5.6% |
| create | instance_group | 0.17 | 0.17 | +0 | +0.0% |
| create | inventory_source | 0.20 | 0.19 | -10 | -5.0% |
| create | job | 0.26 | 0.27 | +10 | +3.8% |
| create | job_template | 0.19 | 0.18 | -10 | -5.3% |
| create | notification_template | 0.17 | 0.17 | +0 | +0.0% |
| create | workflow_job_template | 0.18 | 0.18 | +0 | +0.0% |
| create | project0 | 0.35 | 0.32 | -30 | -8.6% |
| create | workflow_job_template_node | 0.17 | 0.16 | -10 | -5.9% |
| create | project1 | 0.35 | 0.31 | -40 | -11.4% |

**Gateway-native endpoint latencies — list responses, basic auth (mean, seconds):**

| Endpoint | Pre Mean | Post Mean | Delta (ms) | Delta (%) |
| --- | --- | --- | --- | --- |
| application | 0.14 | 0.14 | +0 | +0.0% |
| authenticator | 0.13 | 0.13 | +0 | +0.0% |
| authenticator_maps | 0.13 | 0.13 | +0 | +0.0% |
| organization | 0.16 | 0.16 | +0 | +0.0% |
| role_definition | 0.16 | 0.16 | +0 | +0.0% |
| role_team_assignment | 0.13 | 0.13 | +0 | +0.0% |
| role_user_assignment | 0.14 | 0.13 | -10 | -7.1% |
| service_cluster | 0.15 | 0.15 | +0 | +0.0% |
| setting | 0.13 | 0.12 | -10 | -7.7% |
| team | 0.18 | 0.18 | +0 | +0.0% |
| tokens | 0.14 | 0.13 | -10 | -7.1% |
| user | 0.37 | 0.24 | -130 | -35.1% |

**Gateway-native endpoint latencies — create responses, basic auth (mean, seconds):**

| Test Type | Endpoint | Pre Mean | Post Mean | Delta (ms) | Delta (%) |
| --- | --- | --- | --- | --- | --- |
| create | organization | 0.27 | 0.28 | +10 | +3.7% |
| create | user | 0.36 | 0.34 | -20 | -5.6% |
| create | team | 0.31 | 0.30 | -10 | -3.2% |

**Summary:**

- **Controller endpoints (proxied through gateway):** Of 24 list endpoints, 5 showed a +10ms increase (credential_types, instances, instance_groups, me, notification_templates, workflow_job_templates), 4 showed a -10ms improvement, and 14 were unchanged. All deltas are at the measurement precision floor (0.01s) and within the stddev of each endpoint. Of 15 get/create endpoints, 5 improved by 10–40ms, 1 increased by 10ms (job create), and 9 were unchanged.
- **Gateway-native endpoints:** Of 12 list endpoints, 9 were unchanged, 3 improved by 10ms, and the `user` list endpoint improved dramatically (-130ms, -35.1%). Of 3 create endpoints, 1 increased by 10ms (organization), 2 improved. The `user` list improvement (0.37s → 0.24s) is a genuine change likely attributable to code changes unrelated to dispatcherd between the two builds.
- **CPU median** increased by 0.60 pp (9.82% → 10.42%), well within normal run-to-run variance. Max CPU (15.03%) is comparable to the baseline (15.16%).
- **Memory used median** increased by ~1.4 MB (+5.0%), from 29.4 MB to 30.9 MB. This is a modest increase consistent with dispatcherd's worker processes and within acceptable bounds for the gateway.
- **Network I/O** shows a slight increase (inbound +1.7%, outbound +4.6%), consistent with normal variance and dispatcherd's pg_notify listener traffic.
- **Disk writes** are virtually unchanged (400,539 MB vs 400,444 MB baseline median).

**Verdict: No performance regression from adding dispatcherd.** All acceptance criteria are met.

#### Acceptance Criteria

- No significant performance regression from adding dispatcherd
- Endpoint mean/median latencies remain within ~10% of baseline values
- Gateway CPU median utilization does not meaningfully increase (baseline: ~10%)
- Gateway memory used does not meaningfully increase (baseline: ~29 MB)
- Results documented above for direct comparison

---

## Known Issues

### psycopg 3.2.3 did not deliver same-connection notifications (RESOLVED)

**Discovered**: 2026-04-30 during AAP-65393 dev testing
**Resolved**: 2026-05-01 — confirmed fixed in psycopg 3.2.10

During initial dev testing with psycopg 3.2.3, dispatcherd's pg_notify broker self-check always failed because notifications sent by a connection to itself were not delivered through the `notifies()` API. This caused:

```
RuntimeError: self check message for broker <id> did not arrive in 30.x seconds
```

The workaround was `"max_connection_idle_seconds": None` in the broker config to disable the self-check. After upgrading to psycopg 3.2.10 (required for dispatcherd compatibility), same-connection notifications work correctly and no workaround is needed. The broker self-check now functions as designed.

If a future psycopg regression reintroduces this issue, set `"max_connection_idle_seconds": None` in the pg_notify broker config to disable the self-check without affecting core functionality.

---

## Progress Tracker

| Story | Summary | Status | Depends On |
| --- | --- | --- | --- |
| [AAP-65393](https://redhat.atlassian.net/browse/AAP-65393) | Implement dispatcherd in Gateway | Complete | — |
| [AAP-65394](https://redhat.atlassian.net/browse/AAP-65394) | Add dispatcherd to supervisord config | In Review | AAP-65393 |
| [AAP-65395](https://redhat.atlassian.net/browse/AAP-65395) | Add dispatcherd health check to ping | Backlog | AAP-65393 |
| [AAP-65396](https://redhat.atlassian.net/browse/AAP-65396) | Update Gateway container build | Backlog | AAP-65393 |
| [AAP-65397](https://redhat.atlassian.net/browse/AAP-65397) | Baseline performance test | Backlog | AAP-65396 |
