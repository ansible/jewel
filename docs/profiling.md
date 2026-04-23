# Request Profiling

Gateway includes a built-in profiling layer that instruments both the HTTP
API (Django middleware) and the gRPC external auth layer (Envoy ext_authz).

Every request automatically gets `X-Request-ID` (trace context) and timing
headers. cProfile and SQL metrics are individually opt-in.

## Enabling Profiling

Profiling is controlled by two independent Django settings, both defaulting
to `False`.

### Environment variable (recommended)

Gateway uses Dynaconf with the `GATEWAY_` prefix, so any `GATEWAY_<SETTING>`
environment variable overrides the corresponding Django setting at startup.

```bash
# Enable cProfile .prof file generation (heavy - use for debugging sessions only)
export GATEWAY_ANSIBLE_BASE_PROFILING_ENABLED=true

# Enable SQL query metrics (moderate overhead)
export GATEWAY_ANSIBLE_BASE_PROFILING_SQL_ENABLED=true

# Restart the gateway process
```

For containerized deployments, add the variable to the pod spec or
`docker-compose.yml`. For systemd, add it to the service environment file.

### Django settings file

```python
# settings_dev.py or custom settings override
ANSIBLE_BASE_PROFILING_ENABLED = True
ANSIBLE_BASE_PROFILING_SQL_ENABLED = True
```

## Settings Reference

| Setting | Default | Description |
|---|---|---|
| `ANSIBLE_BASE_PROFILING_ENABLED` | `False` | Enables cProfile output. Writes `.prof` files and adds the `X-API-Profile-File` header. Equivalent to AWX's `AWX_REQUEST_PROFILE`. |
| `ANSIBLE_BASE_PROFILING_SQL_ENABLED` | `False` | Enables SQL query metrics. Adds `X-API-Query-Count` / `X-API-Query-Time` headers and injects trace context into SQL comments. |
| `ANSIBLE_BASE_PROFILING_CPROFILE_DIR` | `'/var/cprofiling/aap_gateway_api'` | Directory where `.prof` files are written. Falls back to the system temp directory if the configured path is not writable. |
| `ANSIBLE_BASE_PROFILING_EXCLUDE_PATHS` | `['/api/gateway/v1/ping/', '/up', '/v3/discovery:']` | URL path prefixes to skip. Matching requests are never profiled, even when the flags are enabled. Timing and trace context still apply. |

All settings can be overridden via environment variables using the `GATEWAY_`
prefix (e.g. `GATEWAY_ANSIBLE_BASE_PROFILING_CPROFILE_DIR=/var/cprofiling`).

> **Warning:** cProfile adds significant performance overhead and should only be enabled temporarily while troubleshooting issues. When enabled, response headers expose absolute filesystem paths (`X-API-Profile-File`, `X-GRPC-Auth-Profile-File`). Do not enable profiling in production without network-level controls to prevent these headers from reaching external clients.

## Response Headers

When profiling is active, instrumentation headers are added to responses.
There are two sets: one for the HTTP API layer and one for the gRPC auth layer.

### HTTP API Headers

These are set by `ObservabilityMiddleware` on Django HTTP responses.

| Header | When present | Description |
|---|---|---|
| `X-Request-ID` | Always | Unique request identifier. Echoes client-provided value or generates a new UUID. |
| `X-API-Total-Time` | Always | Wall-clock request duration (e.g. `0.045s`). |
| `X-API-Profile-File` | `ANSIBLE_BASE_PROFILING_ENABLED` | Filesystem path to the `.prof` file **on the gateway node**. |
| `X-API-Query-Count` | `ANSIBLE_BASE_PROFILING_SQL_ENABLED` | Number of SQL queries executed during the request. |
| `X-API-Query-Time` | `ANSIBLE_BASE_PROFILING_SQL_ENABLED` | Total time spent executing SQL queries. |

### gRPC Auth Headers

These are set by `ExternalAuth._check_with_profiling()` and forwarded through
Envoy to the client as response headers.

| Header | When present | Description |
|---|---|---|
| `X-GRPC-Auth-Time` | Any profiling flag | Wall-clock duration of the gRPC auth check. |
| `X-GRPC-Auth-Node` | Any profiling flag | `CLUSTER_HOST_ID` of the node that handled the auth check. |
| `X-GRPC-Auth-Profile-File` | `ANSIBLE_BASE_PROFILING_ENABLED` | Filesystem path to the `.prof` file **on the gateway node**. |
| `X-GRPC-Auth-Query-Count` | `ANSIBLE_BASE_PROFILING_SQL_ENABLED` | Number of SQL queries during auth. |
| `X-GRPC-Auth-Query-Time` | `ANSIBLE_BASE_PROFILING_SQL_ENABLED` | Total time spent in SQL during auth. |

### Trace Context (always active)

The `X-Request-ID` header is set on every response regardless of profiling
state. If the client sends an `X-Request-ID`, it is echoed back; otherwise one
is generated. This ID is also used as the `.prof` filename.

## Working with .prof Files

The `X-API-Profile-File` and `X-GRPC-Auth-Profile-File` headers contain
**filesystem paths on the gateway node**, not URLs. You need shell access to
retrieve and analyze them.

### Retrieving files

```bash
# From a Kubernetes pod
kubectl cp <pod>:<path> ./profile.prof

# From a local dev environment
cp /tmp/cprofile-*.prof ./profiles/
```

### Analyzing profiles

```bash
# Interactive browser
python -m snakeviz profile.prof

# Top functions by cumulative time
python -c "
import pstats
p = pstats.Stats('profile.prof')
p.sort_stats('cumulative').print_stats(20)
"

# Compare two profiles
python -c "
import pstats
p = pstats.Stats('before.prof')
p.add('after.prof')
p.sort_stats('cumulative').print_stats(20)
"
```

### SQL query analysis

The query count and time headers provide a quick signal for database-bound
requests. For example, if `X-API-Query-Count: 47` and `X-API-Query-Time: 0.800s`
on a request with `X-API-Total-Time: 0.900s`, the bottleneck is query volume rather
than Python code.

When SQL profiling is enabled, SQL queries also include trace context as comments
(trace ID, route, origin) which appear in `pg_stat_activity` and slow query
logs for cross-referencing.

## Architecture

```
Client Request
    |
    v
Envoy Proxy
    |--- gRPC ext_authz ---> ExternalAuth.Check()
    |                            |
    |                            +-- any flag enabled? --> _check_with_profiling()
    |                            |     optional cProfile + optional SQL metrics
    |                            |     X-GRPC-Auth-* headers
    |                            |
    |                            +-- no flags? --> _ExternalAuth.Check() (no overhead)
    |
    v
Django (ObservabilityMiddleware - auto-installed)
    |
    +-- Always: X-Request-ID + X-API-Total-Time
    |
    +-- ANSIBLE_BASE_PROFILING_ENABLED? --> cProfile + X-API-Profile-File
    |
    +-- ANSIBLE_BASE_PROFILING_SQL_ENABLED? --> SQL metrics + X-API-Query-Count/Time
    |
    v
Response (with profiling headers)
```
