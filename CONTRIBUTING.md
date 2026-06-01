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
* **Git hooks**: Run `make git_hooks_config` to enable pre-commit linting checks.
* **Tests**: Always run tests through tox, not pytest directly:
  ```
  tox -e py312
  ```
  See [TESTING.md](TESTING.md) for the full testing guide.
* **Linting**: Run `make lint` to auto-format with ruff.
* **Docker**: Run `make docker-compose` to start a full development environment.

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

