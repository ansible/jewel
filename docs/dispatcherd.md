# Dispatcherd Integration in Gateway

Epic: [AAP-59888](https://redhat.atlassian.net/browse/AAP-59888)

> **This document is a living specification.** It serves as the single source of truth for the dispatcherd integration work. Multiple contributors (each using Claude Code) will work on different stories — read this doc into context before starting any work, and update the relevant sections when your work is complete. Keep descriptions precise; other sessions will rely on them to understand what exists, what the constraints are, and what is left to do.

## How to Use This Document

1. **Before starting work**: Read this entire doc. Check the [Current State](#current-state) section and the [Progress Tracker](#progress-tracker) to understand what has been completed.
2. **While working**: Follow the specifications in the relevant section. Do not deviate from stated interfaces, file paths, naming, or behavioral contracts without updating this doc first.
3. **After completing work**: Update the relevant section — replace `<!-- TODO -->` markers with actual details (file paths created, config keys used, example output, etc.). Update the [Current State](#current-state) summary and mark your story as complete in the [Progress Tracker](#progress-tracker).

## Current State

<!-- Update this section after each story is completed so the next person gets a quick snapshot. -->

**Last updated**: 2026-04-30

AAP-65393 (core implementation) is code-complete and ready for review. The dispatch module, management commands, settings defaults, app config wiring, and unit tests are all in place. No stories have been merged yet.

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
| `psycopg_connection_from_django()` | `ansible_base.lib.utils.db` (DAB) | Obtain a raw psycopg connection from Django's DB config |

### References

- [dispatcherd README](https://github.com/ansible/dispatcherd/blob/main/README.md)
- [dispatcherd configuration docs](https://github.com/ansible/dispatcherd/blob/main/docs/config.md)
- EDA's implementation can be used as a reference for management commands

---

## Specifications by Story

### AAP-65393: Implement dispatcherd in Gateway

**Story**: [AAP-65393](https://redhat.atlassian.net/browse/AAP-65393) | **Status**: In Progress

This is the foundational story. All other stories depend on it.

#### Requirements

| Item | Specification |
| --- | --- |
| Dependency | Add `dispatcherd` to `requirements/requirements.in` |
| Module location | `aap_gateway_api/dispatch/` |
| Config | `config.py` — use `CLUSTER_HOST_ID` (Django setting) for the node name. Configure a broadcast queue. Config dict is passed to dispatcherd's `run_service()`. |
| Management commands | `aap_gateway_api/management/commands/dispatcherd.py` and `dispatcherctl.py` |
| Unit tests | `aap_gateway_api/tests/dispatch/` — cover config module and management commands |
| DB connection | Use DAB's `psycopg_connection_from_django()` from `ansible_base.lib.utils.db` |

#### Constraints

- Do **not** create a custom `GatewayTaskWorker` subclass — use dispatcherd's built-in `TaskWorker` directly.
- Keep the initial configuration minimal: enough for dispatcherd to start, listen, and process tasks.

#### Files Created / Modified

- Created: `aap_gateway_api/dispatch/__init__.py`
- Created: `aap_gateway_api/dispatch/config.py` — `get_dispatcherd_config()` and `_get_conninfo()`
- Created: `aap_gateway_api/dispatch/pre_fork.py` — pre-fork Django setup (closes DB/cache connections before fork)
- Created: `aap_gateway_api/management/commands/dispatcherd.py` — runs the service
- Created: `aap_gateway_api/management/commands/dispatcherctl.py` — control interface (alive, status, etc.)
- Created: `aap_gateway_api/tests/dispatch/__init__.py`
- Created: `aap_gateway_api/tests/dispatch/test_config.py` — 5 tests for config module
- Created: `aap_gateway_api/tests/dispatch/test_management_commands.py` — 4 tests for management commands
- Modified: `requirements/requirements.in` — added `dispatcherd`
- Modified: `aap_gateway_api/defaults.py` — added `DISPATCHERD_MIN_WORKERS = 2`, `DISPATCHERD_MAX_WORKERS = 4`
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

The `conninfo` string is built from `settings.DATABASES["default"]` using the same approach as EDA (host, port, dbname, user, password, SSL options). The `sync_connection_factory` points to DAB's `psycopg_connection_from_django` which reuses Django's existing DB connection.

---

### AAP-65394: Add dispatcherd to supervisord configuration

**Story**: [AAP-65394](https://redhat.atlassian.net/browse/AAP-65394) | **Status**: Backlog
**Depends on**: AAP-65393

#### Requirements

| Item | Specification |
| --- | --- |
| Config file | `tools/configs/supervisord.conf` |
| Program block | `[program:dispatcher]` |
| Command | `/usr/bin/aap-gateway-manage dispatcherctl start` |
| Group | Add `dispatcher` to the `gateway-processes` group |
| `autorestart` | `true` |
| `stopasgroup` | `false` |
| `killasgroup` | `false` |

#### Constraints

- `stopasgroup` and `killasgroup` must be `false` so dispatcherd can be independently restarted without affecting other Gateway processes.

#### Files Modified

<!-- TODO: Confirm exact changes to supervisord.conf once complete -->

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

**Endpoint latencies — list responses, basic auth (seconds):**

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
| settings | 0.15 | 0.15 | 0.14 | 0.16 | 0.01 | 36 | 7.02 |

**Endpoint latencies — get/create responses, basic auth (seconds):**

| Test Type | Endpoint | Mean | Median | Min | Max | Stddev | Rounds | Ops/s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| get | settings | 0.15 | 0.15 | 0.14 | 0.16 | 0.01 | 36 | 7.02 |
| create | credential | 0.18 | 0.18 | 0.17 | 0.19 | 0.01 | 29 | 5.76 |
| create | credential_type | 0.15 | 0.15 | 0.15 | 0.16 | 0.01 | 35 | 6.77 |

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

<!-- TODO: After the dispatcherd container build (AAP-65396) ships and a perf run completes,
     fill in the sections below using the same format as the baseline above.

Source: [raw result doc <doc_id>](<full_url>)
NVR: `<nvr>`
Topology: `cont-b` | Installation: `containerized`
Run window: <start> – <end> UTC

**Gateway resource utilization:**

| Metric | Max | Median | Stddev | P99 |
| --- | --- | --- | --- | --- |
| CPU avg across cores | | | | |
| CPU max core | | | | |
| CPU user% avg | | | | |
| CPU system% avg | | | | |
| CPU iowait% avg | | | | |
| Memory used | | | | |
| Memory free | | | | |
| Disk writes | | | | |
| Network inbound | | | | |
| Network outbound | | | | |

**Endpoint latencies — list responses, basic auth (seconds):**

(Copy the full endpoint table from the baseline and fill with post-dispatcherd values)

**Endpoint latencies — get/create responses, basic auth (seconds):**

(Copy the get/create table from the baseline and fill with post-dispatcherd values)
-->

#### Acceptance Criteria

- No significant performance regression from adding dispatcherd
- Endpoint mean/median latencies remain within ~10% of baseline values
- Gateway CPU median utilization does not meaningfully increase (baseline: ~10%)
- Gateway memory used does not meaningfully increase (baseline: ~29 MB)
- Results documented above for direct comparison

---

## Progress Tracker

| Story | Summary | Status | Depends On |
| --- | --- | --- | --- |
| [AAP-65393](https://redhat.atlassian.net/browse/AAP-65393) | Implement dispatcherd in Gateway | In Progress | — |
| [AAP-65394](https://redhat.atlassian.net/browse/AAP-65394) | Add dispatcherd to supervisord config | Backlog | AAP-65393 |
| [AAP-65395](https://redhat.atlassian.net/browse/AAP-65395) | Add dispatcherd health check to ping | Backlog | AAP-65393 |
| [AAP-65396](https://redhat.atlassian.net/browse/AAP-65396) | Update Gateway container build | Backlog | AAP-65393 |
| [AAP-65397](https://redhat.atlassian.net/browse/AAP-65397) | Baseline performance test | Backlog | AAP-65396 |
