[![codecov](https://codecov.io/github/ansible/jewel/graph/badge.svg?token=F4wilI4Cwj)](https://codecov.io/github/ansible/jewel)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=ansible_jewel&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=ansible_jewel)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=ansible_jewel&metric=coverage)](https://sonarcloud.io/summary/new_code?id=ansible_jewel)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=ansible_jewel&metric=vulnerabilities)](https://sonarcloud.io/summary/new_code?id=ansible_jewel)
[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=ansible_jewel&metric=security_rating)](https://sonarcloud.io/summary/new_code?id=ansible_jewel)
[![Bugs](https://sonarcloud.io/api/project_badges/measure?project=ansible_jewel&metric=bugs)](https://sonarcloud.io/summary/new_code?id=ansible_jewel)
[![Code Smells](https://sonarcloud.io/api/project_badges/measure?project=ansible_jewel&metric=code_smells)](https://sonarcloud.io/summary/new_code?id=ansible_jewel)
[![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=ansible_jewel&metric=sqale_rating)](https://sonarcloud.io/summary/new_code?id=ansible_jewel)
[![Unit Tests](https://github.com/ansible/jewel/workflows/Unit%20Tests/badge.svg)](https://github.com/ansible/jewel/actions/workflows/unit-tests.yml)
[![Linting](https://github.com/ansible/jewel/workflows/Linting/badge.svg)](https://github.com/ansible/jewel/actions/workflows/linting.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

# Jewel

Jewel provides the source code for the Gateway that connects Ansible services and provides common resources.

> The project name, Jewel, refers to a precious stone known as the Eye of the Sea from the same novel that originated the word Ansible, Ursula K. Le Guin's *Rocannon's World*.
> Ansible communicates across distance; Jewel is what everything converges on.

## Container Image

A pre-built container image is published to the GitHub Container Registry on every push to the `devel` branch. The published image does **not** include the platform UI.

```bash
docker pull ghcr.io/ansible/jewel:latest
docker run -p 8000:8000 ghcr.io/ansible/jewel:latest
```

Available tags:

| Tag | Description |
|---|---|
| `latest` | Most recent build from `devel` |
| `sha-<short>` | Pinned to a specific commit (short SHA) |
| `sha-<full>` | Pinned to a specific commit (full SHA) |

To build locally with the platform UI included:

```bash
docker build --target jewel-ui -f tools/docker/Dockerfile .
```

## Communication

Join the Ansible forum:

- [Get Help](https://forum.ansible.com/c/help/6): get help or help others. Please add appropriate tags if you start new discussions, for example the `jewel` tag.
- [Bullhorn newsletter](https://docs.ansible.com/ansible/devel/community/communication.html#the-bullhorn): used to announce releases and important changes.
- [Social Spaces](https://forum.ansible.com/c/chat/4): gather and interact with fellow enthusiasts.
- [News & Announcements](https://forum.ansible.com/c/news/5): track project-wide announcements including social events.

For more information about communication, see the [Ansible communication guide](https://docs.ansible.com/ansible/devel/community/communication.html).

## Contributing to this project

### How to open an issue

If you want to report a bug or request a new feature, please:

1. Search in the [issues](https://github.com/ansible/jewel/issues) for similar reports/requests.
2. If there are already no such issues, open a new one by clicking the `New issue` button.

### Contributor guidelines

Please read the [Contributor Guide](CONTRIBUTING.md) before opening a pull request or submitting an issue.

## AI-Assisted Project

**This project was substantially coded by Large Language Models (LLMs) with human review.**

- **[AI Attribution](https://aiattribution.github.io/):** AIA PAI SeCeNc Hin R Claude Code (Opus, Sonnet & Haiku) v1.0
