# Removing the REST xDS control plane

The gateway serves Envoy configuration over gRPC ADS (CDS, LDS and SDS on one
stream, port 50051). The original REST-JSON endpoints (`/v3/discovery:*`) are
deprecated but still served, for two reasons: bootstraps that have not moved to
`ads_config` poll them, and they are the rollback path. This guide covers how
to remove them cleanly when that is no longer needed.

Every place that exists only for the REST path carries a `REST-XDS-REMOVAL`
comment. Start with:

```bash
grep -rn "REST-XDS-REMOVAL" --include="*.py" --include="*.j2" --include="*.md" .
```

## 1. Gate: when it is safe

Remove the REST path only when **all** of these hold:

- Every supported Envoy bootstrap uses `ads_config` for CDS and LDS: the
  operator configmap, the containerized installer `envoy.yaml`, and the jewel
  dev role. No supported release still renders a REST `api_config_source`.
- At least one full release has shipped with the `Deprecation: true` header and
  ADS-only bootstraps, so downgrade paths no longer need REST.
- You accept that rollback then means image **and** bootstrap, not a bootstrap
  revert alone.

SDS needs no bootstrap change: it follows the transport of the listener that
references it (see "How the REST/ADS split works" below).

## 2. Order of operations

1. **jewel PR** (this repo): remove the code below. Safe once the gate holds.
2. **Template PRs** (operator, installer, dev role): delete the
   `gateway-control-plane-rest` cluster from the bootstraps. It is dead after
   step 1, so this can follow at leisure, but do not do it first: REST-polling
   gateways still need it.
3. **CI cleanup**: the `xds_refresh_delay_seconds` overrides are already dead
   for ADS bootstraps (see section 5).

## 3. jewel code removal

| Where | Remove |
|---|---|
| `aap_gateway_api/views/api/envoy/rest_control_plane.py` | the whole module (views, `XDSDeprecationMixin`) |
| `aap_gateway_api/urls.py` | the three `v3/discovery:*` routes and the view import |
| `aap_gateway_api/utils/xds_configs.py` | `_rest_sds_config`, `_SDS_CONFIG_BUILDERS`; inline `_ads_sds_config()` into `transport_socket()` and drop its `sds_transport` parameter |
| `aap_gateway_api/models/http_port.py` | the `sds_transport` parameter of `get_xds_listener_config` |
| `aap_gateway_api/utils/xds_resources.py` | `XDS_CACHE_KEY_LDS_REST`, `XDS_COMPANION_CACHE_KEYS` (and its loop in `invalidate_xds_cache`), `_LDS_CACHE_KEYS`; drop `sds_transport` from `collect_listeners` and use `XDS_CACHE_KEY_LDS` directly |
| `aap_gateway_api/defaults.py` | `SDS_CLUSTER_NAMES`, `SDS_REFRESH_DELAY_PROTOBUF_DURATION` |

Unchanged on purpose: the ADS servicer and watcher, the signals, the startup
cache clear, and `dump_xds` (all use the shared collectors).

## 4. Tests: port before you delete

`tests/views/api/envoy/test_xds.py`, `test_rest_control_plane.py` and
`test_rest_control_plane_perf.py` exercise listener and cluster *generation*
through the REST endpoints. They are the main coverage of generated xDS content
(routes, listener config, query-count bounds). **Port those assertions to
`collect_clusters()` / `collect_listeners()` (or the ADS servicer) before
deleting the files.** Delete only the REST-specific tests:

- the `Deprecation` header tests and JSON response-shaping tests;
- `test_lds_serves_rest_sds_source` and the `*_rest_*` tests in
  `tests/utils/test_xds_resources.py` and `tests/test_constants.py`;
- cache assertions on `XDS_CACHE_KEY_LDS_REST`.

Keep `tests/views/api/envoy/conftest.py` (cache clearing) if any test still
uses it.

## 5. Docs and CI

- `docs/configuring_envoy.md`: drop the REST endpoint and rollback text.
- The design spec in `docs/superpowers/specs/` can be left as history.
- `xds_refresh_delay_seconds` is only consumed by REST `refresh_delay`. Delete
  the variable from `tools/configs/container-startup.yml` and the `sed`
  overrides in `.github/workflows/dev-environment.yml` and
  `.github/workflows/spec-sync-on-merge.yml`.

## 6. Verify

- `grep -rn "REST-XDS-REMOVAL"` returns nothing.
- `grep -rnE "sds_transport|XDS_CACHE_KEY_LDS_REST|SDS_CLUSTER_NAMES|gateway-control-plane-rest|v3/discovery"`
  returns nothing across jewel, the operator, and the installer.
- Full test suite passes; in the dev environment `config_dump` shows ADS for
  CDS, LDS and SDS and `POST /v3/discovery:listeners` is a 404.

## How the REST/ADS split works (why the code looks the way it does)

A listener's SDS config source must match the transport the listener arrives
on. An Envoy that polls LDS over REST has no `ads_config`, and Envoy rejects a
listener whose SDS source is `ads` (`ADS must be configured to support an ADS
config source`). So the REST view serves listeners with a REST SDS source and
the ADS servicer serves them with an `ads` source. The two variants differ in
content, so they are cached under separate keys, and invalidating the LDS key
drops both. This keeps an image/bootstrap version split harmless and keeps
rollback a bootstrap-only revert, until the REST path is removed.

## Separate, later: legacy cache keys

Gateway versions before ADS cached JSON dicts under `xds:cds`, `xds:lds` and
`xds:sds`. `XDS_LEGACY_CACHE_KEYS` (marked `LEGACY-XDS-KEYS-REMOVAL`) deletes
those on invalidation and startup. Remove it once no supported upgrade-from
release writes them. This is independent of the REST removal.
