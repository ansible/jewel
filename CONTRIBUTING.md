# Contributing to the Jewel project

The Jewel project is [licensed under Apache 2.0](LICENSE) and accepts contributions through GitHub pull requests.
We are very happy to receive contributions from the community in any form.

## Principles

This repository adheres to the following principles:

* **Open**: Contribution is always welcome.
* **Respectful**: See the [Code of Conduct](CODE-OF-CONDUCT.md).
* **Transparent and accessible**: Work and collaboration should be done in public.
* **Merit**: Ideas and contributions are accepted according to their merit and alignment with the project objectives and principles.

## Certificate of Origin

By contributing to Jewel, you agree to the Developer Certificate of Origin (DCO).
This document was created by the Linux Kernel community and is a simple statement that you, as a contributor, have the legal right to make the contribution.
See the [DCO](DCO) file for details.

## How to contribute

### Reporting bugs

Open a [GitHub issue in the `ansible/jewel` repo](https://github.com/ansible/jewel/issues) with a clear description of the problem.
The [bug report template](https://github.com/ansible/jewel/issues/new?template=bug_report.yml) will guide you through providing the necessary information.

### Suggesting enhancements

Open a [GitHub issue in the `ansible/jewel` repo](https://github.com/ansible/jewel/issues) or start a discussion on the [community forum](https://forum.ansible.com) with the [`jewel` tag](https://forum.ansible.com/tag/jewel/) before investing time in a large change.
Describe the problem you are solving and why the existing behavior is insufficient.

### Submitting pull requests

1. Fork the repository and create a branch from `devel`.
2. Make your changes. Keep commits focused and well-described.
3. Run the linter and tests before pushing:
   ```
   make lint
   tox -e py312
   ```
4. Submit a pull request against `devel`. Complete the [pull request template](https://github.com/ansible/jewel/blob/devel/.github/PULL_REQUEST_TEMPLATE.md) and reference any related issues.
5. Sign off your commits to agree to the [DCO](DCO).

## Where to contribute

### Authentication backends

Jewel supports several authentication methods including:

* SAML
* OIDC
* LDAP
* TACACS+
* local username/password
* HTTP basic auth
* OAuth2 personal access tokens
* service-to-service JWT authentication

Most of these backends are implemented through [django-ansible-base](https://github.com/ansible/django-ansible-base) (see [`ansible_base/authentication/`](https://github.com/ansible/django-ansible-base/tree/devel/ansible_base/authentication)).
We welcome contributions that add new authentication backends or improve existing ones.

Here are some starting points:

* `aap_gateway_api/authentication/`: Jewel-specific auth backends
* `aap_gateway_api/tests/authentication/`: authentication tests

### Performance optimizations

Jewel proxies requests to downstream services through an Envoy-based proxy layer that uses HTTP/REST based configuration with gRPC authentication.
We welcome contributions that improve proxy throughput, JWT validation efficiency, and cache performance.

Here are some starting points:

* `aap_gateway_api/proxy/`: control plane and service auth
* `aap_gateway_api/utils/jwt_cache.py`: JWT session caching
* `docs/profiling.md`: built-in profiling tools

### Documentation and examples

We welcome tutorials, deployment guides, and integration pattern documentation.
You can find existing docs in the `docs/` directory.

### Bug reports and fixes

Bug fixes are always welcome, especially around edge cases in authentication flows, proxy routing, and session management.
See [Reporting Bugs](#reporting-bugs) above.

## Development setup

* **Python**: 3.11 or later (3.12 preferred)
* **[uv](https://docs.astral.sh/uv/)**: Required for regenerating `requirements.txt` (`make requirements`). Install from https://docs.astral.sh/uv/.
* **Git hooks**: Run `make git_hooks_config` to enable pre-commit linting checks.
* **Tests**: Always run tests through tox, not pytest directly:
  ```
  tox -e py312
  ```
  See [TESTING.md](TESTING.md) for the full testing guide.
* **Linting**: Run `make lint` to auto-format with ruff.
* **Development environment**: Jewel requires Podman 4.9.3 or later and `podman-compose` 1.6.0 or later. On macOS, install Podman and start its virtual machine before creating the development environment:
  ```
  brew install podman
  podman machine init
  podman machine start
  ```
  On Linux, install Podman through the distribution package manager. Then create and activate a Python virtual environment before installing the development tools and starting the stack:
  ```
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements/requirements_dev.txt
  make podman-preflight
  make podman-compose
  ```
  This installs `ansible`, `tox`, `ruff`, and `podman-compose` into the active virtual environment. When `container-startup.yml` is first created, the Makefile selects port 443 for confirmed rootful Podman and 8443 otherwise; set `proxy_port` in that file to override it.

  To use the local Keycloak development provider, set `keycloak_enabled: True` in
  `container-startup.yml` before running `make podman-compose`. See the
  [Keycloak development environment](docs/authentication.md#keycloak-development-environment)
  for the configured authenticators and token helper.

## Updating the OpenAPI specification

The OpenAPI specification (`openapi.yaml`) is generated from code with
drf-spectacular and committed to the repository. When you change an API
endpoint, regenerate the spec and commit it alongside your code — CI fails if
the committed spec drifts from the code:

```
make genschema
git add openapi.yaml
```

`make genschema` runs inside the `jewel-ci:devel` container with a temporary
sqlite3 database. On stable branches, override the container tag:

```
make genschema GENSCHEMA_TAG=stable-2.5
```

If your change modifies the API surface, also add a changelog fragment under
`changelogs/fragments/` describing the change. CI warns when a spec change has
no fragment and uploads a skeleton fragment as an artifact that you can fill
in.
### Local SQL Server mode

The local Compose stack can run Gateway against SQL Server. Set `mssql_enabled: true` in the workspace's `container-startup.yml`, optionally override `mssql_sa_password`, then start the stack with `make podman-compose` (or the `make docker-compose` alias). The SQL Server 2025 Developer container creates the `gateway` database before Gateway starts, and Keycloak runs on its embedded development database so the stack needs no PostgreSQL container. PostgreSQL remains Gateway's database when `mssql_enabled` is false.

SQL Server's self-signed certificate is trusted only in local development and test settings. The default SQL Server memory limit is 2048 MB and can be changed with `mssql_memory_limit_mb` in `container-startup.yml`.

### Microsoft ODBC driver rule

**Gateway images must never contain Microsoft's ODBC driver binaries** — neither the `msodbcsql18` RPM nor the `mssql-python-odbc` wheel (which ships the same driver libraries):

- Published images (GHCR `jewel`, quay `jewel-ci`) build without the driver — the GHCR workflow builds with `INCLUDE_MSSQL_DRIVER=false` and fails if any `libmsodbcsql*` binary is found in the image.
- The driver is installed or configured at runtime/startup instead: CI installs the RPM in the SQL Server job, and `launch-gateway` registers the driver library from the locally pip-installed `mssql-python-odbc` wheel via `ODBCSYSINI` when the database engine is SQL Server (the development image installs that wheel because it is built and used only on your machine and is never published).
- A local runtime image may opt in with `--build-arg INCLUDE_MSSQL_DRIVER=true --build-arg ACCEPT_MS_ODBC_EULA=Y`; the resulting image is local-only and must not be published. See the [Microsoft ODBC Driver license](https://github.com/microsoft/mssql-python/blob/main/mssql_python_odbc/licenses/MICROSOFT_ODBC_DRIVER_FOR_SQL_SERVER_LICENSE.txt).

**License acceptance for local development**: starting the Compose stack with `mssql_enabled: true` requires explicit acceptance of the [Microsoft ODBC Driver license](https://github.com/microsoft/mssql-python/blob/main/mssql_python_odbc/licenses/MICROSOFT_ODBC_DRIVER_FOR_SQL_SERVER_LICENSE.txt). After reviewing and accepting it, record the acceptance and retry:

```bash
touch .accept-mssql-odbc-eula
```

The marker file is git- and container-ignored. The check runs on every SQL Server mode startup, cached image or not; PostgreSQL mode skips it entirely.

## Code quality

Jewel uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting.
Pre-commit hooks in `.githooks/` enforce these checks on staged files automatically.

CI runs the following checks, and more, on every pull request:

* `tox -e ruff-check`: lint violations
* `tox -e ruff-format`: formatting violations
* `tox -e check-migrations`: migration consistency
* `tox -e check-oauth2-permissions`: OAuth2 permission validation

NOTE: A pull request can not be merged with any failing CI issues.

## Getting help

If you have a question or are unsure whether a contribution is wanted, please join us on the [community forum](https://forum.ansible.com) and ask there.
You can use the [`jewel` tag](https://forum.ansible.com/tag/jewel/) to filter existing topics in the forum.
