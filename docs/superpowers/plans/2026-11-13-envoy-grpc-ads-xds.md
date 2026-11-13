# Envoy xDS over gRPC ADS — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve Envoy's CDS and LDS configuration over a gRPC Aggregated Discovery Service (ADS) stream from the gateway's existing gRPC server, pushed on config change, alongside the (now-deprecated) REST xDS views.

**Architecture:** Resource collection (queries, protobuf packing, digest versioning, caching) is extracted from the REST views into a shared module. A new ADS servicer on the existing gRPC server (port 50051, same processes as ext_authz) serves per-Envoy streams; a per-process watcher thread polls the existing payload cache keys and broadcasts pushes to connected streams when a rebuild's digest differs from the last pushed version. SDS stays on REST. The jewel dev bootstrap template switches CDS/LDS to `ads: {}`.

**Tech Stack:** Python 3.12, Django, grpcio 1.68.1 + `xds-protos` 1.68.1 (already pinned; ships `envoy.service.discovery.v3.ads_pb2_grpc`), pytest.

**Spec:** `docs/superpowers/specs/2026-11-13-envoy-grpc-ads-xds-design.md`

## Global Constraints

- No new dependencies — `xds-protos==1.68.1` already provides the ADS servicer stubs.
- REST view behavior is unchanged except: responses now carry `version_info`, and a `Deprecation: true` header. Existing REST tests must pass without modification to their assertions (import-line updates are allowed).
- SDS stays on REST: `SecretDiscoverServiceView` keeps its current caching rule (always caches), CDS/LDS keep theirs (only cache non-empty responses).
- No feature flags or new settings; the watcher interval is a constructor default, not a Django setting.
- The gRPC server forks 5 worker processes (`start_grpc_server.py`); any thread (watcher, per-stream readers) must be started **inside** `_run_server` (post-fork), never at import time or in `Command.handle`.
- Lint must pass before each commit: `ruff check . && ruff format --check .` (line length 160).
- Tests run via `tox -e py312 -- <test path> -v`. Full suite: `tox -e py312 -- -m "not perf"`.
- Commit messages: `NO_JIRA: <summary>` (replace `NO_JIRA` with the JIRA ticket if one is assigned), ending with an `Assisted-by: <model> <noreply@...>` line per repo convention.
- Implement on a fresh branch off `devel` (current checkout has unrelated in-flight work on `AAP-101667-retry-connect-failure`).

## Review Focus

1. **Digest instability** — same DB state must produce the same `version` across rebuilds, or every watcher tick becomes a push. Test: Task 1, `test_digest_stable_across_rebuilds`.
2. **Push churn on spurious invalidation** — a cache invalidation that rebuilds identical config must not push. Test: Task 3, `test_tick_no_push_when_digest_unchanged`.
3. **Empty-config rebuild storm** — with zero routes/ports the CDS/LDS cache entries are never set (no-cache-empty rule), so the watcher collects every tick; it must still not broadcast (digest unchanged). Test: Task 3, `test_tick_empty_db_no_broadcast`.
4. **Thread start before fork** — starting the watcher at import time or in `Command.handle` produces broken threads in the 5 forked workers. Pinned by the Global Constraint; verified in Task 4 by code placement inside `_run_server`.
5. **Stream/thread leak on disconnect** — an Envoy disconnecting must remove its stream from the registry so the watcher stops queueing to it. Test: Task 2, `test_stream_removed_from_registry_on_context_inactive`.

---

### Task 1: Shared resource collectors

**Files:**
- Create: `aap_gateway_api/utils/xds_resources.py`
- Modify: `aap_gateway_api/views/api/envoy/rest_control_plane.py`
- Modify: `aap_gateway_api/signals/xds_cache.py:13` (import from new module)
- Modify: `aap_gateway_api/apps.py:32` (import from new module)
- Modify: `aap_gateway_api/tests/views/api/envoy/conftest.py`, `test_rest_control_plane.py`, `test_rest_control_plane_perf.py` (import paths only)
- Test: `aap_gateway_api/tests/utils/test_xds_resources.py` (new)

**Interfaces:**
- Consumes: nothing new (moves code from `rest_control_plane.py`).
- Produces (later tasks rely on these exact names):
  ```python
  # Amended (final review C1): a "v2" namespace so pickled ResourceSets never
  # share a key with the pre-ADS dict format on the shared redis.  The legacy
  # "xds:cds"/"xds:lds"/"xds:sds" keys are also deleted by invalidate_xds_cache
  # (hence by the startup clear and the signals), via XDS_LEGACY_CACHE_KEYS.
  XDS_CACHE_KEY_CDS = "xds:v2:cds"
  XDS_CACHE_KEY_LDS = "xds:v2:lds"
  XDS_CACHE_KEY_SDS = "xds:v2:sds"

  @dataclass
  class ResourceSet:
      version: str        # sha256 hex digest of the packed resources
      resources: list     # list[google.protobuf.any_pb2.Any], packed

  def invalidate_xds_cache(*keys: str) -> None
  def collect_clusters(resource_names: list[str] | None = None) -> ResourceSet
  def collect_listeners(resource_names: list[str] | None = None) -> ResourceSet
  def collect_secrets() -> ResourceSet
  ```

- [ ] **Step 1: Write the failing tests**

In `aap_gateway_api/tests/utils/test_xds_resources.py`, using the existing fixtures `unauthenticated_api_client` is NOT needed — these are unit-level:

```python
@pytest.mark.django_db
def test_collect_clusters_round_trips_through_cache(full_service_hierarchy_controller):
    first = collect_clusters()
    assert cache.get(XDS_CACHE_KEY_CDS) is not None
    second = collect_clusters()
    assert second.version == first.version

@pytest.mark.django_db
def test_digest_stable_across_rebuilds(full_service_hierarchy_controller):
    first = collect_clusters()
    invalidate_xds_cache(XDS_CACHE_KEY_CDS)
    second = collect_clusters()
    assert second.version == first.version

@pytest.mark.django_db
def test_digest_changes_when_route_changes(full_service_hierarchy_controller):
    first = collect_clusters()
    route = full_service_hierarchy_controller.route
    route.gateway_path = "/changed/"
    route.save()  # fires the signal that invalidates the cache
    second = collect_clusters()
    assert second.version != first.version

@pytest.mark.django_db
def test_collect_clusters_caching_rule():
    # The no-cache-empty rule, expressed invariantly because post_migrate
    # may seed default gateway data in the test DB:
    rs = collect_clusters()
    if rs.resources == []:
        assert cache.get(XDS_CACHE_KEY_CDS) is None
    else:
        assert cache.get(XDS_CACHE_KEY_CDS) is not None
```

Also add the same cache-round-trip test for `collect_listeners` and `collect_secrets` (SDS always caches — assert `cache.get(XDS_CACHE_KEY_SDS) is not None` even when empty).

- [ ] **Step 2: Run tests to verify they fail**

Run: `tox -e py312 -- aap_gateway_api/tests/utils/test_xds_resources.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aap_gateway_api.utils.xds_resources'`

- [ ] **Step 3: Implement `aap_gateway_api/utils/xds_resources.py`**

Move the three cache-key constants and `invalidate_xds_cache` from `rest_control_plane.py`. Implement the three collectors by moving the query/assembly bodies out of the view `post()` methods (`rest_control_plane.py:103-162`): the CDS queryset + `_max_route_timeout` pre-computation, the LDS queryset + gateway-cluster lookup, and the SDS CA-cert assembly. Each collector:

1. Checks `cache.get(key)`; on hit returns the cached `ResourceSet` (do NOT recompute).
2. On miss, builds the resource dict list exactly as the views do today, packs each into `Any` via `ParseDict` + `Pack` (same `symbol_database.Default().pool` dance and proto-import block the views use — move the `# isort: off` proto imports here too).
3. Computes `version = resource_digest(resources)`.
4. Applies the existing caching rule (CDS/LDS: only if non-empty; SDS: always) and returns.

`resource_digest(resources)`: sha256 hex over the concatenation of each `Any.SerializeToString(deterministic=True)`. Order comes from the querysets' existing `order_by` — do not add sorting.

The REST views then become thin: `post()` parses `resource_names` from `request.POST` exactly as `get_qs` does today (preserve current semantics verbatim, including the `"*"` handling), calls the collector, and wraps the result with the existing `get_xds_response` shape — now `DiscoveryResponse(version_info=rs.version, resources=rs.resources)` run through `MessageToDict`. Do not set a nonce on REST responses. Update the three import sites (signals, apps, tests) to import keys/`invalidate_xds_cache` from the new module.

- [ ] **Step 4: Run tests to verify they pass**

Run: `tox -e py312 -- aap_gateway_api/tests/utils/test_xds_resources.py aap_gateway_api/tests/views/api/envoy/ -v`
Expected: PASS — including the existing REST view tests with only their import lines changed. If a REST test assertion fails, the collector changed REST behavior; fix the collector, not the test.

- [ ] **Step 5: Lint and commit**

Run: `ruff check . && ruff format --check .`

```bash
git add aap_gateway_api/utils/xds_resources.py aap_gateway_api/views/api/envoy/rest_control_plane.py aap_gateway_api/signals/xds_cache.py aap_gateway_api/apps.py aap_gateway_api/tests/
git commit -m "NO_JIRA: Extract shared xDS resource collectors from REST views"
```

### Task 2: ADS servicer and stream registry

**Files:**
- Create: `aap_gateway_api/proxy/ads.py`
- Test: `aap_gateway_api/tests/proxy/test_ads.py` (new)

**Interfaces:**
- Consumes: `collect_clusters`, `collect_listeners`, `ResourceSet` from Task 1.
- Produces (Task 3 and 4 rely on these exact names):
  ```python
  CDS_TYPE_URL = "type.googleapis.com/envoy.config.cluster.v3.Cluster"
  LDS_TYPE_URL = "type.googleapis.com/envoy.config.listener.v3.Listener"

  class StreamRegistry:
      def add(self, stream: "_Stream") -> None
      def remove(self, stream: "_Stream") -> None
      def streams(self) -> list["_Stream"]
      def broadcast(self, event: tuple) -> None   # put event on every stream's queue

  class AggregatedDiscoveryService(ads_pb2_grpc.AggregatedDiscoveryServiceServicer):
      def __init__(self, registry: StreamRegistry | None = None) -> None
      def StreamAggregatedResources(self, request_iterator, context) -> Iterator[DiscoveryResponse]
  ```
  Internal `_Stream` shape Task 3 relies on: `stream.events` is a `queue.Queue` of `("request", DiscoveryRequest)` and `("push", type_url)` tuples (amended in the final review: a push is a "type changed" hint, not a payload), and `stream.context` exposes `is_active()`.

- [ ] **Step 1: Write the failing tests**

In `aap_gateway_api/tests/proxy/test_ads.py`. Test harness: a `FakeContext` class with a settable `is_active` flag (starts `True`), and plain `iter([...])` request iterators — the servicer's reader thread consumes them; call the servicer method directly and pull from the returned generator with `next()`.

```python
@pytest.mark.django_db
def test_initial_subscription_returns_current_state(full_service_hierarchy_controller):
    registry = StreamRegistry()
    servicer = AggregatedDiscoveryService(registry=registry)
    req = DiscoveryRequest(type_url=CDS_TYPE_URL)  # no version_info = initial
    ctx = FakeContext()
    gen = servicer.StreamAggregatedResources(iter([req]), ctx)
    resp = next(gen)
    assert resp.type_url == CDS_TYPE_URL
    assert resp.version_info != ""
    assert resp.nonce != ""
    assert len(resp.resources) > 0
    ctx.active = False

@pytest.mark.django_db
def test_ack_with_current_version_sends_nothing(full_service_hierarchy_controller):
    # First response establishes the version; an ACK repeating it must not yield.
    ...  # build gen as above, get resp1; put ("request", DiscoveryRequest(type_url=CDS_TYPE_URL, version_info=resp1.version_info, response_nonce=resp1.nonce)) on the stream's events queue directly; assert no new response within a short timeout (use stream.events.join / poll)

@pytest.mark.django_db
def test_nack_is_logged(full_service_hierarchy_controller, caplog):
    # DiscoveryRequest with error_detail set → logged at WARNING, no response (log-and-drop)
    ...

def test_unknown_type_url_logged_and_ignored(caplog):
    # type_url "type.googleapis.com/envoy.config.route.v3.RouteConfiguration" → WARNING log, no yield
    ...

@pytest.mark.django_db
def test_stream_removed_from_registry_on_context_inactive(full_service_hierarchy_controller):
    registry = StreamRegistry()
    servicer = AggregatedDiscoveryService(registry=registry)
    ctx = FakeContext()
    gen = servicer.StreamAggregatedResources(iter([DiscoveryRequest(type_url=CDS_TYPE_URL)]), ctx)
    next(gen)
    assert len(registry.streams()) == 1
    ctx.active = False
    with pytest.raises(StopIteration):
        next(gen)  # generator loop sees inactive context, cleans up, returns
    assert len(registry.streams()) == 0

def test_nonces_unique_across_responses():
    # Two pushes / two subscriptions → different nonce values
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `tox -e py312 -- aap_gateway_api/tests/proxy/test_ads.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError` on `aap_gateway_api.proxy.ads`

- [ ] **Step 3: Implement `aap_gateway_api/proxy/ads.py`**

Structure:

- `_Stream`: holds `context`, `events: queue.Queue`, `subscribed: set[str]`, and `last_versions: dict[str, str]` — no lock: both are only touched on the generator thread (amended in the final review). `read_requests(request_iterator)` drains the iterator forever, putting `("request", req)` on the queue (daemon thread target; iterator exhaustion or a grpc error ends it, logged at DEBUG with `exc_info`).
- `StreamRegistry`: list + lock; `broadcast` puts the event on each stream's queue.
- `AggregatedDiscoveryService.StreamAggregatedResources(self, request_iterator, context)`:
  1. Create `_Stream`, `registry.add`, start the daemon reader thread.
  2. Generator loop: `while context.is_active():` block on `stream.events.get(timeout=0.5)` (re-loop on `queue.Empty`).
  3. On `("request", req)`: `type_url` not in `{CDS_TYPE_URL, LDS_TYPE_URL}` → `logger.warning`, skip. If `req.error_detail.code != 0` → `logger.warning` with `error_detail.message` (NACK, log-and-drop: send nothing). If it's an ACK whose `version_info` equals the current version for that type → skip. Otherwise call `django.db.close_old_connections()` (pooled gRPC thread), fetch the current `ResourceSet` via the Task 1 collector (a collector exception is logged at WARNING and re-raised, ending the stream), record the version, yield `DiscoveryResponse(version_info=rs.version, nonce=uuid4().hex, resources=rs.resources, type_url=type_url)`.
  4. On `("push", type_url)` (amended in the final review): skip if the stream never subscribed to `type_url`; otherwise re-collect current state the same way as a request (normally a cache hit — never send the broadcast-time state, which can be older than what a request on this stream already sent); if `rs.version == stream.last_versions.get(type_url)` skip; record and yield the same response shape.
  5. `finally: registry.remove(stream)`.
- Collectors map: a module-level dict `{CDS_TYPE_URL: collect_clusters, LDS_TYPE_URL: collect_listeners}`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `tox -e py312 -- aap_gateway_api/tests/proxy/test_ads.py -v`
Expected: PASS

- [ ] **Step 5: Lint and commit**

Run: `ruff check . && ruff format --check .`

```bash
git add aap_gateway_api/proxy/ads.py aap_gateway_api/tests/proxy/test_ads.py
git commit -m "NO_JIRA: Add ADS servicer for Envoy CDS/LDS streaming"
```

### Task 3: Cache watcher

**Files:**
- Create: `aap_gateway_api/proxy/xds_watcher.py`
- Test: `aap_gateway_api/tests/proxy/test_xds_watcher.py` (new)

**Interfaces:**
- Consumes: `StreamRegistry`, `CDS_TYPE_URL`, `LDS_TYPE_URL` (Task 2); `collect_clusters`, `collect_listeners`, `XDS_CACHE_KEY_CDS`, `XDS_CACHE_KEY_LDS`, `invalidate_xds_cache` (Task 1).
- Produces (Task 4 relies on):
  ```python
  class XDSWatcher(threading.Thread):
      def __init__(self, registry: StreamRegistry, interval: float = 1.0) -> None  # daemon thread
      def tick(self) -> None    # one poll cycle; also the test entry point
      def stop(self) -> None
  ```

> **Amended in the final review (m2/I4/m1):** the sketches below reflect the original silent-prime design. As implemented, the first tick with a registered stream broadcasts one `("push", type_url)` hint per type (no silent prime; `test_first_tick_hints_current_state`, `test_tick_warm_cache_first_tick_then_change`, `test_tick_empty_db_broadcasts_only_first_observation`), pushes carry only the `type_url`, `tick()` is a no-op with zero registered streams (`test_tick_is_noop_without_streams`), and the startup race is covered end-to-end (`test_stream_subscribed_before_first_tick_gets_intervening_change`). See `aap_gateway_api/tests/proxy/test_xds_watcher.py`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_tick_pushes_on_model_change(full_service_hierarchy_controller):
    registry = StreamRegistry()
    stream = make_fake_stream()  # register a bare _Stream with a FakeContext via registry.add
    watcher = XDSWatcher(registry)
    watcher.tick()  # primes baseline (first observation, silently)
    assert stream.events.empty()  # nothing pushed without a change
    # make a real CDS-affecting model change (e.g. flip is_service_https on a Service),
    # then invalidate_xds_cache(XDS_CACHE_KEY_CDS) — on_commit receivers don't fire in tests
    watcher.tick()
    kind, (type_url, rs) = stream.events.get(timeout=1)
    assert kind == "push" and type_url == CDS_TYPE_URL and rs.version != ""
    # and no LDS push followed a CDS-only change

@pytest.mark.django_db
def test_tick_no_push_when_digest_unchanged(full_service_hierarchy_controller):
    # Prime, model change + invalidate, tick (pushes once), invalidate again
    # WITHOUT any model change, tick → queue must stay empty
    # (identical rebuild produces the same digest — the digest, not the
    # cache miss, is the change signal)
    ...

@pytest.mark.django_db
def test_tick_empty_db_no_broadcast():
    registry = StreamRegistry()
    stream = make_fake_stream()
    watcher = XDSWatcher(registry)
    watcher.tick()   # collects empty (uncached) — must not broadcast
    watcher.tick()   # still empty — must not broadcast
    assert stream.events.empty()

@pytest.mark.django_db
def test_tick_pushes_cds_before_lds(full_service_hierarchy_controller):
    # Make CDS- and LDS-affecting model changes, invalidate both keys; one
    # tick must queue CDS push before LDS push
    ...

@pytest.mark.django_db
def test_tick_warm_cache_prime_is_silent(full_service_hierarchy_controller):
    # Pre-warm the cache (run another watcher's tick, or call the collector
    # directly), then start a NEW watcher: its first tick observes the cached
    # version and must not push; a subsequent model change + invalidate must
    # push (the warm-start case for workers started after the first)

@pytest.mark.django_db
def test_two_watchers_share_one_cache(full_service_hierarchy_controller):
    # Two watchers with separate registries on one cache (the 5-forked-worker
    # topology): a model change + invalidate → BOTH watchers push to their
    # own streams (the first to rebuild re-caches; the other must see the
    # new version on its cache hit and still push)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `tox -e py312 -- aap_gateway_api/tests/proxy/test_xds_watcher.py -v`
Expected: FAIL with import error

- [ ] **Step 3: Implement `aap_gateway_api/proxy/xds_watcher.py`**

`XDSWatcher(threading.Thread, daemon=True)` with a `threading.Event` stop flag; `run()` loops `tick()` + `stop_event.wait(interval)`. `tick()`:

0. (Amended in the final review.) Return immediately if `registry.streams()` is empty — no polling cost in workers without ADS streams.
1. `django.db.close_old_connections()` (long-lived thread; connections are never recycled by request signals).
2. `cached = cache.get_many([XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS])`.
3. For each `(type_url, key, collector)` in a CDS-first ordered list: `rs = cached.get(key)`, treating a value that is not a `ResourceSet` as a miss; if it is a miss, `rs = collector()` (which re-caches non-empty results). The digest comparison runs on EVERY tick, hit or miss — the cache is shared by all forked workers and every node, so the cache miss is not a reliable per-worker change signal: if `rs.version != self._last_versions.get(type_url)`, update `_last_versions` and `registry.broadcast(("push", type_url))`. This includes the first observation of a type (amended in the final review: no silent prime — a stream that subscribed before the first tick may be stale; streams suppress versions they already hold).
4. The whole body is wrapped in `try/except Exception: logger.exception(...)` so a transient DB/redis error degrades one tick instead of silently killing the watcher thread.

Note in a code comment why empty configs re-collect every tick (the no-cache-empty rule) and why that's accepted: after the first observation no broadcast fires, and truly-empty deployments are transitional.

- [ ] **Step 4: Run tests to verify they pass**

Run: `tox -e py312 -- aap_gateway_api/tests/proxy/test_xds_watcher.py -v`
Expected: PASS

- [ ] **Step 5: Lint and commit**

Run: `ruff check . && ruff format --check .`

```bash
git add aap_gateway_api/proxy/xds_watcher.py aap_gateway_api/tests/proxy/test_xds_watcher.py
git commit -m "NO_JIRA: Add xDS cache watcher that pushes ADS updates on invalidation"
```

### Task 4: Wire ADS into the gRPC server

**Files:**
- Modify: `aap_gateway_api/management/commands/start_grpc_server.py:25-52`

**Interfaces:**
- Consumes: `AggregatedDiscoveryService`, `StreamRegistry` (Task 2), `XDSWatcher` (Task 3).
- Produces: a running ADS service on the existing `GRPC_SERVER_PORT`; nothing imports this.

- [ ] **Step 1: Implement the wiring**

In `_run_server`: create one `StreamRegistry`, one `XDSWatcher(registry)`, register `AggregatedDiscoveryService(registry)` via `add_AggregatedDiscoveryServiceServicer_to_server`, and `watcher.start()` — all inside `_run_server` (post-fork; see Global Constraints). In debug mode the watcher still runs (single process, interval unchanged). Amended in the final review: debug mode sizes the `ThreadPoolExecutor` at 2 threads (was 1), because an ADS stream holds its worker thread for its lifetime and would otherwise starve ext_authz.

- [ ] **Step 2: Verify the existing suite is unaffected**

Run: `tox -e py312 -- aap_gateway_api/tests/ -m "not perf" -v`
Expected: PASS (no existing test starts the gRPC server; this task only changes the management command)

- [ ] **Step 3: Smoke-check the command starts**

Run: `python aap_gateway_api/manage.py start_grpc_server --debug` in the dev environment (needs the dev DB/settings); confirm the log lines for both the server bind and the watcher start, then stop it.

- [ ] **Step 4: Lint and commit**

Run: `ruff check . && ruff format --check .`

```bash
git add aap_gateway_api/management/commands/start_grpc_server.py
git commit -m "NO_JIRA: Register ADS servicer and xDS watcher in the gRPC server"
```

### Task 5: Deprecation markers on the REST views

**Files:**
- Modify: `aap_gateway_api/views/api/envoy/rest_control_plane.py`
- Test: `aap_gateway_api/tests/views/api/envoy/test_rest_control_plane.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: `Deprecation: true` header on all three REST xDS responses; docstrings state the deprecation. (The views stay `exclude=True` in the OpenAPI schema — they are machine-facing Envoy endpoints deliberately kept out of the API schema, so `deprecated=True` there would be invisible dead code.)

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_cds_response_carries_deprecation_header(unauthenticated_api_client, full_service_hierarchy_controller):
    resp = unauthenticated_api_client.post(reverse("cds"), data={})
    assert resp.status_code == 200
    assert resp["Deprecation"] == "true"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `tox -e py312 -- aap_gateway_api/tests/views/api/envoy/test_rest_control_plane.py::test_cds_response_carries_deprecation_header -v`
Expected: FAIL with `KeyError: 'Deprecation'` (assertion on missing header)

- [ ] **Step 3: Implement**

Add a small mixin on `XDSView` overriding `finalize_response` to set `response["Deprecation"] = "true"`. Keep the three views' `@extend_schema(exclude=True)` as-is (no `deprecated=True` — excluded operations never appear in the schema, so the flag would be dead code; the deprecation signal is the header and docstrings). Update each view's docstring to state the REST xDS endpoints are deprecated in favor of ADS.

- [ ] **Step 4: Run tests to verify they pass**

Run: `tox -e py312 -- aap_gateway_api/tests/views/api/envoy/ -v`
Expected: PASS

- [ ] **Step 5: Lint and commit**

Run: `ruff check . && ruff format --check .`

```bash
git add aap_gateway_api/views/api/envoy/rest_control_plane.py aap_gateway_api/tests/views/api/envoy/test_rest_control_plane.py
git commit -m "NO_JIRA: Mark REST xDS control plane endpoints as deprecated"
```

### Task 6: Dev bootstrap template switches to ADS

**Files:**
- Modify: `tools/ansible/roles/proxy-config/templates/envoy.yml.j2:5-24`

**Interfaces:**
- Consumes: the ADS service from Task 4.
- Produces: dev Envoys subscribing via ADS.

- [ ] **Step 1: Edit the template**

Add under `dynamic_resources`:

```yaml
  ads_config:
    api_type: GRPC
    transport_api_version: V3
    grpc_services:
      - envoy_grpc:
          cluster_name: gateway_control_plane
```

Change `cds_config` and `lds_config` to `ads: {}` with `resource_api_version: V3`, removing their REST `api_config_source` blocks. **Keep** the `gateway-control-plane-rest` cluster definition (SDS still uses it).

- [ ] **Step 2: Verify in the dev environment**

Run: `make docker-compose` (or the existing dev flow), then:
1. Envoy comes up and serves traffic (check the Envoy admin UI on port 19000: `GET /config_dump` shows dynamically loaded clusters/listeners with an ADS config source).
2. Change a route via the gateway API → within ~2s the change appears in Envoy's config dump without an Envoy restart.
3. Stop the gateway gRPC server container/process → Envoy keeps serving traffic on last-known-good config (robustness check from the spec).

- [ ] **Step 3: Lint and commit**

Run: `ruff check . && ruff format --check .`

```bash
git add tools/ansible/roles/proxy-config/templates/envoy.yml.j2
git commit -m "NO_JIRA: Switch dev Envoy bootstrap to ADS for CDS/LDS"
```

### Task 7: Documentation

**Files:**
- Modify: `docs/configuring_envoy.md`
- Modify: `docs/superpowers/specs/2026-11-13-envoy-grpc-ads-xds-design.md` (status line only, if desired)

**Interfaces:** None.

- [ ] **Step 1: Update `docs/configuring_envoy.md`**

Add a "Control Plane Configuration" section: CDS/LDS are delivered over gRPC ADS when the Envoy bootstrap uses `ads_config` (the dev environment today) from the gateway's gRPC server (port 50051, same server as ext_authz), pushed on config change; SDS remains on REST polling for now; the REST xDS endpoints (`/v3/discovery:*`) are deprecated but functional and serve as the bootstrap-rollback path; rollback = revert the Envoy bootstrap to REST `api_config_source` blocks and restart Envoy.

- [ ] **Step 2: Commit**

```bash
git add docs/configuring_envoy.md
git commit -m "NO_JIRA: Document ADS control plane and REST xDS deprecation"
```
