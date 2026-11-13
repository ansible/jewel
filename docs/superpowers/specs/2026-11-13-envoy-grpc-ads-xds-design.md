# Envoy xDS over gRPC ADS — Design

Date: 2026-11-13
Status: Approved in conversation (2026-11-13)
Repos touched (phased): `ansible/jewel` first; `ansible/aap-gateway-operator`
and `ansible/aap-containerized-installer` follow before release

## Intent

Replace Envoy's REST-JSON xDS configuration polling (CDS, LDS, SDS) with
gRPC Aggregated Discovery Service (ADS) streaming served from the gateway's
existing gRPC server. Today every Envoy polls the full configuration as
JSON over HTTP on a timer — CDS/LDS every 60s, SDS every 5s — regardless of
whether anything changed. Polling interval and change-propagation latency
are in direct tension: lower the interval and traffic goes up, raise it and
changes take longer to apply. gRPC server-push removes that tension
entirely: configuration is sent once per stream on connect and again only
when it changes.

Success looks like: no xDS polling traffic, config changes propagating to
Envoys within seconds of a model change, no new infrastructure, and a
rollback path that is a bootstrap-template change only.

## Goals

- Eliminate Envoy xDS polling (full-config JSON over HTTP per poll).
- Propagate configuration changes promptly, driven by the existing
  model-signal → cache-invalidation path.
- Reuse the existing resource-building code and cache used by the REST
  views.
- Serve xDS from the existing gRPC server (port 50051) alongside ext_authz.
- Mark the REST xDS views as deprecated while keeping them functional.

## Non-goals

- Delta xDS (incremental updates). State-of-the-world push already
  eliminates polling; delta adds per-stream resource state tracking on the
  server for configs that change rarely. Revisit only if push payloads
  prove to be a problem.
- Health Discovery Service (HDS). Deferred; see "HDS accommodation" below.
- Removing the REST xDS views. Follow-up once gRPC ADS is proven in the
  field.
- Switching SDS to ADS. SDS is rarely used, its config source lives in the
  gateway image (`_rest_sds_config()` in `xds_configs.py`, not the
  bootstrap), and moving it would couple the rollback story to gateway
  image versions. SDS moves to ADS in a later phase, together with REST-view
  removal, when an image+template coordinated change is acceptable.
- Any change to ext_authz behavior.

## Anti-goals

- New infrastructure: no new services, ports, or dependencies (the
  `envoy` proto package already ships ADS servicer stubs).
- Anything visible to end users of the gateway.

## Constraints

- **Envoy has no transport fallback.** `ApiConfigSource` takes exactly one
  `api_type`; there is no try-gRPC-then-REST chain for a resource type.
  Resilience comes from Envoy's last-known-good semantics: on stream loss
  Envoy keeps its applied configuration and keeps proxying, reconnecting
  with backoff. This matches REST behavior today (failed poll = stale
  config, not outage).
- **Bootstrap is rendered in three places**: `jewel/tools/ansible/roles/
  proxy-config/templates/envoy.yml.j2` (dev only), `aap-gateway-operator/
  roles/ansibleautomationplatform/templates/envoy.configmap.yaml.j2`, and
  `aap-containerized-installer/roles/automationgateway/templates/
  envoy.yaml.j2`. The operator and containerized installer are the templates
  actually used in deployments; the jewel role serves local development.
  The jewel PR changes the dev template (so ADS is exercised in the dev
  environment); the operator and installer templates change in follow-up
  PRs once the jewel change is approved for release. The gateway serves
  both transports, so a merged jewel PR is inert until a bootstrap
  template opts in to ADS.
- **SDS is configured inside the generated listener config**, not the
  bootstrap: `_rest_sds_config()` in `aap_gateway_api/utils/xds_configs.py`
  emits a REST `api_config_source` referencing `SDS_CLUSTER_NAMES`. SDS
  stays on REST in this phase (see non-goals), so `_rest_sds_config()` and
  the `gateway-control-plane-rest` bootstrap cluster are unchanged.
- **The gRPC server is 5 forked worker processes** (`GRPC_SERVER_PROCESSES`),
  each a synchronous grpc server with a `ThreadPoolExecutor`
  (`GRPC_SERVER_MAX_THREADS_PER_PROCESS`, currently 10). Stream state and
  push triggers must work per-process.
- **Rolling upgrades**: pods upgrade atomically (Envoy + gateway together),
  but an Envoy's ADS stream may land on a not-yet-upgraded peer pod. The
  stream fails fast (UNIMPLEMENTED) and Envoy retries across the other
  `gateway_control_plane` endpoints, converging on an upgraded pod.
  Transient and self-healing; no mitigation needed beyond verification.
- **Existing cache semantics must be preserved**: shared redis cache whose
  xDS keys are deleted centrally on invalidation (AAP-65886), and the rule
  that empty bootstrap-time responses are not cached. The default
  `DABCacheWithFallback` over plain django_redis does not broadcast
  invalidations; propagation relies on the shared key itself, which every
  node's watcher observes on its next tick.

## Approaches considered

1. **Status quo (REST polling)** — rejected. The polling-vs-latency
   tension is the problem being solved. The redis cache avoids DB rebuilds
   but not the HTTP + JSON wire cost or the per-poll Django request-stack
   overhead.
2. **Separate gRPC streams per resource type** (CDS/LDS/SDS each their own
   gRPC service and stream) — rejected. Server-side code volume is nearly
   identical to ADS (three fixed-type handlers vs one `type_url`-multiplexed
   handler over shared resource building). The Envoy bootstrap needs three
   GRPC `api_config_source` blocks instead of one `ads_config`. And it
   leaves a transient cross-type inconsistency window: listeners reference
   clusters by name, so an LDS push landing before its matching CDS push
   leaves Envoy briefly referencing a missing cluster (Envoy keeps the old
   listener — not an outage, but a wedge risk on every route change).
3. **ADS on the existing gRPC server, state-of-the-world** — chosen. One
   bidi stream per Envoy multiplexing CDS/LDS by `type_url`, served
   from the same server and port as ext_authz. Updates on one stream are
   ordered across types by construction. Costs: single-stream head-of-line
   blocking across types (irrelevant at our config sizes) and modest
   per-stream bookkeeping. This is also Envoy's recommended mode.

## Design

### Server: ADS servicer

New `AggregatedDiscoveryService` servicer
(`envoy.service.discovery.v3.ads_pb2_grpc`, already shipped by the `envoy`
proto dependency) implementing `StreamAggregatedResources(request_iterator,
context)`, registered in `start_grpc_server.py` alongside ext_authz. Lives
in a new module under `aap_gateway_api/proxy/` (exact placement is the
builder's call).

The handler:

- Reads `DiscoveryRequest`s from the stream. On a request with no
  `version_info` (initial subscription), responds with current state for
  that `type_url` from the same cache the REST views use.
- Tracks per-stream subscribed types (CDS and LDS; SDS is not served here
  in this phase). ACKs are consumed and ignored;
  NACKs (requests with `error_detail`) are logged with the detail and
  produce no response — re-sending a rejected version would loop NACKs at
  network speed. The next push with a new version still goes out because
  pushes compare against the last-sent version.
- Sends `version_info` on every response (see versioning below) and a
  `nonce` per response.

Resource collection is refactored out of the REST views into shared
functions (query + `get_xds_*_config` assembly, including the
`_max_route_timeout` pre-computation and the empty-response no-cache rule)
so the REST views and the ADS servicer call the same code. The REST views
keep their response behavior unchanged (the cache keys move to a new
namespace; see "Cache key namespace" below).

### Versioning and push

- `version_info` is a digest of the serialized resources for that type,
  computed at build time and stored inside the cached payload alongside the
  resources.
- There is **no separate version key**. Each gRPC worker process runs a
  lightweight watcher (a daemon thread) that checks the *existing* payload
  cache keys (`xds:v2:cds`, `xds:v2:lds`; see "Cache key namespace" below)
  via `cache.get_many` roughly once per second, and only while the worker has
  at least one connected ADS stream (with none, the tick returns immediately) — a single redis round-trip, not a request through Django.
  On a hit the watcher uses the cached `ResourceSet` (its digest travels
  inside the payload; a cached value that is not a `ResourceSet` is treated
  as a miss); on a miss (invalidation or TTL expiry) it rebuilds
  that type's resources — which re-caches them — and uses the fresh set.
  **The change signal is the digest comparison against the watcher's own
  last-seen version, evaluated on every tick — not the cache miss.** The
  cache is shared by all 5 forked gRPC workers and every gateway node, so
  whichever worker rebuilds first re-caches the entry and the rest see
  hits; only comparing versions on every tick makes every worker's watcher
  push to its own streams. When a type's digest changed, the watcher
  broadcasts a `("push", type_url)` hint to every connected stream; each
  stream subscribed to that type re-collects the current state (normally a
  cache hit) and sends a `DiscoveryResponse` unless it already holds that
  version. Re-collecting, rather than sending the state the watcher saw,
  prevents a late push from rolling a stream back to a version older than
  one a request on the same stream just sent. When both CDS and LDS changed
  within a tick, CDS is pushed before LDS (the ordering benefit of ADS); the
  two cache reads are not atomic, so an LDS change can occasionally be pushed
  one tick before its CDS change.
- The first observation of a type (hit or miss, empty or not) also
  broadcasts. A stream that subscribed before the watcher's first tick, with
  a change landing in between, would otherwise stay stale until the next
  change. Streams that already hold the current version suppress the push
  (the servicer compares against its last-sent version), so this costs at
  most one re-collection per stream.
- This reuses the exact propagation machinery REST polling relies on today:
  `invalidate_xds_cache` deletes the shared-redis key centrally, and every
  node's watcher observes the rebuilt version on its next tick. Introducing
  a separate version key was considered and rejected: the digest already
  travels inside the cached payload, so the watcher gets it from the same
  single `get_many` round-trip, and there is no second key whose writes and
  invalidations must be kept coherent with the payload keys. (jewel's
  default cache is `DABCacheWithFallback` over plain django_redis, which
  does not broadcast invalidations, so cross-node propagation relies solely
  on the shared redis.)
- **Self-heal backstop**: the collectors cache with an explicit
  `timeout=300` (`XDS_CACHE_TIMEOUT`). This must be explicit:
  `DABCacheWithFallback.set` defaults to `timeout=None` (never expires).
  With the TTL, a worker that rebuilds pre-change state after an
  invalidation (an invalidate-then-stale-set race), or any change path that
  bypasses `post_save`/`post_delete` signals, self-heals within ~5 minutes —
  the same guarantee REST polling is meant to provide. One such path exists today
  (`aap_gateway_api/utils/service_id_sync.py` uses a queryset `.update()`
  on ServiceCluster, which fires no signals); this is a pre-existing latent
  issue affecting the REST views equally and is noted, not fixed, here.
- **Cache key namespace**: the cached values are pickled `ResourceSet`
  objects under `xds:v2:cds` / `xds:v2:lds` / `xds:v2:sds`. Pre-ADS gateway
  versions cached `MessageToDict` dicts under `xds:cds` / `xds:lds` /
  `xds:sds` on the same shared redis; sharing those keys during a rolling
  upgrade or downgrade would make old nodes fail to unpickle (which
  `DABCacheWithFallback` treats as an outage: fail over, then clear the
  shared redis on recovery) and new nodes read dicts. `invalidate_xds_cache`
  also deletes each key's legacy counterpart, so the startup clear and the
  signal invalidations remove stale legacy entries. The cleanup is one
  directional: an old node still mid-upgrade invalidates only the legacy
  keys, so a change saved through it leaves new nodes' `xds:v2:*` entries
  stale until their 300s TTL expires — bounded and transitional, and one
  more reason to rehearse a mixed-version window before rollout.
- **Filtered REST requests are not cached**: the REST views pass
  `resource_names` through to the collectors; a filtered collection is
  returned but never written under the shared unfiltered key (which the
  watchers would otherwise push to every Envoy).
- **Debug mode** (`start_grpc_server --debug`) runs a single process with a
  2-thread executor: an ADS stream holds its sync gRPC worker thread for the
  stream's lifetime, so a single thread would starve ext_authz.
- Dispatcherd broadcast into the 5 forked workers was considered and
  rejected as the trigger mechanism: wiring subscriptions into forked
  gRPC workers is awkward, and the cache-key watch achieves the same
  propagation with node-local code.

### Envoy bootstrap changes (both templates)

- Add an `ads_config` block:
  `api_type: GRPC`, `transport_api_version: V3`,
  `grpc_services: [{envoy_grpc: {cluster_name: gateway_control_plane}}]` —
  reusing the gRPC cluster that already exists for ext_authz.
- `cds_config` and `lds_config` become `ads: {}` (with
  `resource_api_version: V3`); their REST `api_config_source` blocks are
  removed from the templates. The `gateway-control-plane-rest` cluster
  **stays** — SDS still references it.
- SDS: unchanged (see non-goals).

### REST views: keep, mark deprecated

The REST views remain functional and unchanged in behavior (shared
resource-collection refactor aside). They gain deprecation indicators:
docstring/`extend_schema` markers and a response `Deprecation` header
(exact mechanism is the builder's call). Beyond the rollback role, they are
the compatibility layer for mixed-version deployments: a new gateway image
can run against an old operator- or installer-rendered bootstrap (REST
CDS/LDS), so the REST sources must keep working for as long as
version-skew between gateway image and bootstrap templates is possible.
Deprecation is documentation-only; there is no near-term removal.

### Rollback

Rollback is a bootstrap change only: revert the envoy template (operator
configmap or installer) to the REST `api_config_source` blocks for
CDS/LDS and restart Envoy. SDS never moved, and the
`gateway-control-plane-rest` cluster was never removed, so nothing in the
gateway image depends on the new bootstrap. No gateway code or image
rollback is involved.

### Release coordination

- The jewel PR lands first and is safe to merge independently: serving ADS
  alongside REST is additive, and deployment bootstraps keep polling REST
  until their templates change.
- The operator and containerized-installer template PRs follow once the
  change is approved for release; they are what activate ADS in
  deployments. Within a release the components are bundled, but customers
  can run a new gateway image against old-rendered bootstrap templates
  during upgrades — covered by the REST compatibility above.
- Backport target is 2.7 only; the RPM installer and ansible collection
  are out of scope.

### HDS accommodation

HDS is deferred and needs a solid argument for beating the current
CDS-embedded active health checks before it's built. The design keeps it a
drop-in: HDS is its own service and stream (it cannot ride ADS), so adding
it later means one more servicer registered in `start_grpc_server.py` and
its own handler module — no re-architecture of anything in this design.

### Operational notes

- ADS streams are long-lived and each occupies a thread in the sync grpc
  server's pool for its lifetime (10 threads per process, 5 processes per
  pod). Expected steady state is ~1 stream per pod (one Envoy per gateway
  pod, round-robin across pods and processes), but LB skew is possible.
  Watch thread utilization in larger clusters; the mitigation if needed is
  bumping `GRPC_SERVER_MAX_THREADS_PER_PROCESS` or a dedicated process for
  xDS — noted here so it isn't rediscovered.
- No feature flag: transport selection lives entirely in the Envoy
  bootstrap templates. The gateway serving both transports simultaneously
  costs nothing.

### Documentation and tests

- Update `docs/configuring_envoy.md` for the new bootstrap shape and the
  REST deprecation.
- Unit tests for the servicer: initial subscription returns current
  resources per type; version change triggers a push; NACK logging; nonce
  and version correctness.
- The REST perf tests' query-count-bounded assertions carry over to the
  shared collection functions.
- Dev-environment verification (docker-compose): config change propagates
  to Envoy without restart; killing the gRPC server leaves Envoy serving
  traffic on last-known-good config (the robustness claim, demonstrated).

## What's left to the builder

- Module placement and class structure for the servicer and watcher.
- The digest function used for `version_info`.
- Watcher interval and backoff details.
- The deprecation mechanism on the REST views.
- gRPC test scaffolding (fake stream/context vs in-process server).
- Operator and installer template PR contents (deferred until the jewel
  change is approved for release).
