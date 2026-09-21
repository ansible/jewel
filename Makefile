SHELL=/bin/bash

# Prefer python 3.12 but take python3 if 3.12 is not installed
PYTHON := $(notdir $(shell for i in python3.12 python3; do command -v $$i; done|sed 1q))
CHECK_SYNTAX_FILES ?= aap_gateway_api/
RM ?= /bin/rm
UID := $(shell id -u)
TOX_ARGS ?= ""
PODMAN ?= podman
PODMAN_COMPOSE ?= podman-compose --in-pod false
PODMAN_MIN_VERSION ?= 5.0.0
PODMAN_COMPOSE_MIN_VERSION ?= 1.6.0
PODMAN_ROOTLESS := $(shell podman info --format '{{.Host.Security.Rootless}}' 2>/dev/null || true)
DEFAULT_PROXY_PORT := $(if $(filter false,$(PODMAN_ROOTLESS)),443,8443)

COMPOSE_OPTS ?=
COMPOSE_UP_OPTS ?=
ADMIN_PASSWORD ?= $(shell $(PYTHON) -c "import secrets; print(secrets.token_urlsafe(20))")
GATEWAY_ABS_PATH := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
UNAME_S := $(shell uname -s)
PODMAN_COLLECTION_STAMP := tools/generated/.podman-collection-installed
SOURCES_STAMP := tools/generated/.sources-generated
SOURCES_INPUTS := tools/ansible/generate-sources.yml tools/ansible/vars/container_config.yml \
	$(shell find tools/ansible/roles/sources -type f) \
	tools/configs/container-startup.yml container-startup.yml requirements/requirements_git.txt
PROXY_CONFIG_INPUTS := tools/ansible/generate-proxy-configs.yml tools/ansible/vars/container_config.yml \
	$(shell find tools/ansible/roles/proxy-config -type f) container-startup.yml

.PHONY: PYTHON_VERSION clean git_hooks_config compose-build podman-compose-build docker-compose-build \
	check lint check_ruff check_ruff_format \
	podman-compose-basic podman-compose podman-compose-detached podman-compose-attach podman-compose-down \
	podman-reset podman-reset-volumes \
	docker-compose-basic docker-compose docker-compose-detached docker-compose-attach docker-compose-down \
	docker-reset docker-reset-volumes plumb update_django_ansible_base_hash \
	collection podman-collection podman-preflight requirements check-requirements tools/generated/sources \
	ci-image ci-image-push

## Get the version of python we are working with
PYTHON_VERSION:
	@echo "$(subst python,,$(PYTHON))"

## Set the local git configuration(specific to this repo) to look for hooks in .githooks folder
git_hooks_config:
	git config --local core.hooksPath .githooks

## Zero out all of the temp and build files
clean:
	@-find . -type f -regex ".*\.py[co]$$" -print0 | xargs -0 $(RM) -f
	@-find . -type d -name "__pycache__" -print0 \
			 -o -type d -name ".pytest_cache" -print0 | xargs -0 $(RM) -rf

# Test targets
# -------------------------------------

## Run test suite
check:
	tox

## Run unit tests (excludes perf tests)
check_test:
	tox -e py312 -- -m "not perf"

## Run performance/scaling tests only
check_perf:
	tox -e py312 -- -m perf -v

## Run linters (and modify files if necessary)
lint:
	tox -m lint

## Run ruff format check
check_ruff_format:
	tox -e ruff-format -- --check $(CHECK_SYNTAX_FILES)

## Run ruff linting check
check_ruff:
	tox -e ruff-check -- $(CHECK_SYNTAX_FILES)

check_help_text:
	export GATEWAY_SECRET_KEY_FILE=tools/configs/dev_secret_key; python -m aap_gateway_api help_text_check --applications aap_gateway_api --ignore-file ./.help_text_check.ignore


# HELP related targets
# --------------------------------------

HELP_FILTER=.PHONY

## Display help targets
help:
	@printf "Available targets:\n"
	@$(MAKE) -s help/generate | grep -vE "\w($(HELP_FILTER))"


## Display help for all targets
help/all:
	@printf "Available targets:\n"
	@$(MAKE) -s help/generate

## Generate help output from MAKEFILE_LIST
help/generate:
	@awk '/^[-a-zA-Z_0-9%:\\\.\/]+:/ { \
		helpMessage = match(lastLine, /^## (.*)/); \
		if (helpMessage) { \
			helpCommand = $$1; \
			helpMessage = substr(lastLine, RSTART + 3, RLENGTH); \
			gsub("\\\\", "", helpCommand); \
			gsub(":+$$", "", helpCommand); \
			printf "  \x1b[32;01m%-35s\x1b[0m %s\n", helpCommand, helpMessage; \
		} else { \
			helpCommand = $$1; \
			gsub("\\\\", "", helpCommand); \
			gsub(":+$$", "", helpCommand); \
			printf "  \x1b[32;01m%-35s\x1b[0m %s\n", helpCommand, "No help available"; \
		} \
	} \
	{ lastLine = $$0 }' $(MAKEFILE_LIST) | sort -u
	@printf "\n"

# Container related targets
# --------------------------------------

## Fetch service key
fetch-service-key:
	ansible-playbook tools/ansible/fetch-service-key.yml -e @container-startup.yml
## Migrate service data to services
migrate-service-data:
	ansible-playbook tools/ansible/migrate-service-data.yml -e @container-startup.yml



## Start Podman containers without additional playbooks
podman-compose-basic: $(SOURCES_STAMP) tools/generated/proxy.yml compose-build git_hooks_config
	env UID=${UID} $(PODMAN_COMPOSE) -f tools/generated/compose.yml $(COMPOSE_OPTS) up --remove-orphans $(COMPOSE_UP_OPTS)

## Start the Podman containers, plumb sidecars, and register service proxies
podman-compose: podman-compose-detached register-services plumb
	@if [[ ! "${COMPOSE_UP_OPTS}" =~ "-d" ]] ; then \
		env UID=${UID} $(PODMAN_COMPOSE) -f tools/generated/compose.yml up --no-recreate; \
	fi

## Start the Podman containers in detached mode and wait for readiness
podman-compose-detached: $(SOURCES_STAMP) tools/generated/proxy.yml compose-build git_hooks_config podman-collection
	env UID=${UID} PODMAN_COMPOSE="${PODMAN_COMPOSE}" ansible-playbook tools/ansible/initialize-containers.yml -e @container-startup.yml -e @tools/ansible/vars/container_config.yml;
	env UID=${UID} $(PODMAN_COMPOSE) -f tools/generated/compose.yml $(COMPOSE_OPTS) up --detach --remove-orphans $(COMPOSE_UP_OPTS) --wait;

## Attach to the Podman container logs after a detached start
podman-compose-attach: $(SOURCES_STAMP) podman-preflight
	env UID=${UID} $(PODMAN_COMPOSE) -f tools/generated/compose.yml up --no-recreate

## Stop and remove Podman Compose containers and networks, preserving named volumes
podman-compose-down: podman-preflight
	if [ -f tools/generated/compose.yml ] ; then env UID=${UID} $(PODMAN_COMPOSE) -f tools/generated/compose.yml $(COMPOSE_OPTS) down ; fi

## Delete Podman containers, networks, volumes, and generated files
podman-reset: $(SOURCES_STAMP) podman-preflight
	if [ -f tools/generated/compose.yml ] ; then $(PODMAN_COMPOSE) -f tools/generated/compose.yml down -v ; fi
	rm -fr tools/generated/{,.[!.],..?}*
	touch tools/generated/.gitkeep

## Remove Podman container volumes and networks
podman-reset-volumes: $(SOURCES_STAMP) podman-preflight
	if [ -f tools/generated/compose.yml ] ; then $(PODMAN_COMPOSE) -f tools/generated/compose.yml down -v ; fi

## Backward-compatible alias for podman-compose-basic
docker-compose-basic: podman-compose-basic

## Backward-compatible alias for podman-compose
docker-compose: podman-compose

## Backward-compatible alias for podman-compose-detached
docker-compose-detached: podman-compose-detached

## Backward-compatible alias for podman-compose-attach
docker-compose-attach: podman-compose-attach

## Backward-compatible alias for podman-compose-down
docker-compose-down: podman-compose-down

## Backward-compatible alias for podman-reset
docker-reset: podman-reset

## Backward-compatible alias for podman-reset-volumes
docker-reset-volumes: podman-reset-volumes

## Generate the container-startup.yml file
container-startup.yml: tools/configs/container-startup.yml
	@if [ -f container-startup.yml ] ; then \
		cp container-startup.yml container-startup.yml.backup; \
		echo ">>>>>> WARNING <<<<<<<<" ; \
		echo "container-startup.yml has been overwritten but a backup was taken (will be overwritten on next change)!"; \
	fi;
	@sed \
	    -e "s/gateway_admin_password: .*/gateway_admin_password: '$(ADMIN_PASSWORD)'/" \
	    -e "s/^proxy_port: .*/proxy_port: $(DEFAULT_PROXY_PORT)/" \
	    tools/configs/container-startup.yml > ./container-startup.yml

## Backward-compatible target for generating container sources
tools/generated/sources: $(SOURCES_STAMP)

## Generate all container source files
$(SOURCES_STAMP): $(SOURCES_INPUTS)
	ansible-playbook tools/ansible/generate-sources.yml \
	    -e @tools/ansible/vars/container_config.yml \
	    -e @container-startup.yml
	touch $@

## Install the Ansible collection used by Podman-specific container setup
podman-collection: $(PODMAN_COLLECTION_STAMP)

$(PODMAN_COLLECTION_STAMP): requirements/requirements.yml
	ansible-galaxy collection install --force -r requirements/requirements.yml
	touch $@

collection:
	@if [ -d ansible.platform ]; then \
		echo "Installing collection from ansible.platform"; \
		cd ansible.platform; \
		ansible-galaxy collection build . --force; \
		ansible-galaxy collection install ansible-platform-*.tar.gz --force; \
		cd ..; \
	else \
		echo "Installing collection from github"; \
		if ! ansible-galaxy collection install git+https://github.com/ansible/ansible.platform.git; then \
			echo "HTTPS clone failed, falling back to SSH..."; \
			ansible-galaxy collection install git@github.com:ansible/ansible.platform.git; \
		fi; \
	fi;
	pip install requests

## Canonical Podman Compose build target
podman-compose-build: compose-build

## Backward-compatible alias for compose-build
docker-compose-build: compose-build

## Build the Compose containers
compose-build: $(SOURCES_STAMP) podman-preflight update_django_ansible_base_hash tools/generated/.has_built_api

API_TARGETS = tools/generated/.django_ansible_base_head tools/generated/Containerfile.dev_env tools/configs/uwsgi.ini tools/configs/supervisord.conf requirements/requirements.txt requirements/requirements_dev.txt tools/scripts/auto-reload tools/configs/nginx.conf $(shell find tools -type f -name "*gateway*") $(shell find tools/ansible -type f)
ifndef HEADLESS
    API_TARGETS += tools/generated/.has_built_ui
endif
## Build the API container
tools/generated/.has_built_api: $(API_TARGETS)
	mkdir -p django-ansible-base/requirements
	$(eval GATEWAY_NODE_COUNT=$(shell grep 'gateway_node_count' container-startup.yml | sed 's:[^0-9]::g')) \
	$(eval GATEWAY_NODES=$(shell seq 1 ${GATEWAY_NODE_COUNT} | sed 's:^:gateway:g' | xargs)) \
	$(PODMAN_COMPOSE) -f tools/generated/compose.yml \
	    build \
	    --build-arg DJANGO_ANSIBLE_BASE_DEVEL_SHA=$(shell cat tools/generated/.django_ansible_base_head) \
	    ${GATEWAY_NODES}
	touch $@

## Internal target for target tools/generated/.django_ansible_base_head
update_django_ansible_base_hash:
	@if [ ! -d "django-ansible-base/.git" ]; then \
		echo "Checking for updates to django-ansible-base"; \
		$(eval DAB_HEAD=$(shell git ls-remote https://github.com/ansible/django-ansible-base | awk '/refs\/heads\/devel/ { print $$1 }')) \
		if [[ ! -f tools/generated/.django_ansible_base_head ]] || ! grep -q $(DAB_HEAD) tools/generated/.django_ansible_base_head; then \
			echo "UPDATE - django-ansible-base is out of date, triggering rebuild"; \
			echo $(DAB_HEAD) > tools/generated/.django_ansible_base_head; \
		else \
			echo "NO UPDATE - django-ansible-base is up to date"; \
		fi; \
	else \
		echo "Not checking for django-ansible-base update because a local checkout of it was found."; \
		if [[ ! -f tools/generated/.django_ansible_base_head ]] || ! grep -qx local tools/generated/.django_ansible_base_head; then \
			echo local > tools/generated/.django_ansible_base_head; \
		fi; \
	fi

## Generate the tools/generated/.django_ansible_base_head file for tracking django-ansible-base
tools/generated/.django_ansible_base_head: update_django_ansible_base_hash

## Check to pull the latest platform-ui if needed
tools/generated/.has_built_ui: podman-preflight
	$(PODMAN) pull quay.io/ansible/platform-ui:latest > tools/generated/last_ui_pull
	if [ ! -f $@ ] || [ `cat tools/generated/last_ui_pull | grep "Image is up to date" | wc -l` == "0" ] ; then \
	    echo "Updating UI"; \
	    touch $@ ; \
	fi

## Build the cert file
tools/generated/gateway.crt:
	openssl req -nodes -newkey rsa:2048 -keyout tools/generated/gateway.key -out tools/generated/gateway.csr -subj "/C=US/ST=North Carolina/L=Durham/O=Ansible/OU=Gateway Development/CN=localhost"
	openssl x509 -req -days 365 -in tools/generated/gateway.csr -signkey tools/generated/gateway.key -out tools/generated/gateway.crt
ifeq ($(UNAME_S),Linux)
	chmod 440 tools/generated/gateway.crt tools/generated/gateway.key
endif

## Build the proxy config file
tools/generated/proxy.yml: $(PROXY_CONFIG_INPUTS)
	ansible-playbook tools/ansible/generate-proxy-configs.yml -e @tools/ansible/vars/container_config.yml -e @container-startup.yml

## Verify the local Podman and podman-compose versions meet the supported minimums
podman-preflight:
	@set -eu; \
	version_at_least() { \
		awk -v actual="$$1" -v minimum="$$2" 'BEGIN { \
			split(actual, actual_parts, "."); \
			split(minimum, minimum_parts, "."); \
			for (part = 1; part <= 3; part++) { \
				if ((actual_parts[part] + 0) > (minimum_parts[part] + 0)) exit 0; \
				if ((actual_parts[part] + 0) < (minimum_parts[part] + 0)) exit 1; \
			} \
			exit 0; \
		}'; \
	}; \
	if ! command -v "$(word 1,$(PODMAN))" >/dev/null 2>&1; then \
		echo "Error: Podman is required. Install Podman $(PODMAN_MIN_VERSION) or newer."; \
		exit 1; \
	fi; \
	podman_version="$$($(PODMAN) version --format '{{.Client.Version}}' 2>/dev/null || true)"; \
	if [ -z "$$podman_version" ] || ! version_at_least "$$podman_version" "$(PODMAN_MIN_VERSION)"; then \
		echo "Error: Podman $(PODMAN_MIN_VERSION) or newer is required (found: $${podman_version:-unknown})."; \
		exit 1; \
	fi; \
	if ! command -v "$(word 1,$(PODMAN_COMPOSE))" >/dev/null 2>&1; then \
		echo "Error: podman-compose is required. Install podman-compose $(PODMAN_COMPOSE_MIN_VERSION) or newer."; \
		exit 1; \
	fi; \
	podman_compose_version="$$($(word 1,$(PODMAN_COMPOSE)) --version 2>/dev/null | awk '/podman-compose/ { print; exit }' | sed -E 's/[^0-9]*([0-9]+(\.[0-9]+){1,2}).*/\1/')"; \
	if [ -z "$$podman_compose_version" ] || ! version_at_least "$$podman_compose_version" "$(PODMAN_COMPOSE_MIN_VERSION)"; then \
		echo "Error: podman-compose $(PODMAN_COMPOSE_MIN_VERSION) or newer is required (found: $${podman_compose_version:-unknown})."; \
		exit 1; \
	fi; \
	echo "Using Podman $$podman_version and podman-compose $$podman_compose_version."

## Regenerate requirements.txt from requirements.in
requirements: requirements/requirements.in
	cd requirements && ./updater.sh run

## Verify requirements.txt is in sync with requirements.in
check-requirements:
	cd requirements && ./updater.sh check

## Register services and ports
register-services: tools/generated/proxy.yml collection
	ansible-playbook tools/ansible/register-services.yml -e @container-startup.yml -e @tools/generated/proxy.yml

## Remove the services and ports generated from the register-services target
cleanup-services: tools/generated/proxy.yml collection
	ansible-playbook tools/ansible/register-services.yml -e @container-startup.yml -e @tools/generated/proxy.yml -e gateway_state=absent

## Plumb the sidecar containers
plumb:
	ansible-playbook tools/ansible/plumb.yml -e @tools/ansible/vars/container_config.yml -e @container-startup.yml

# CI Image
# --------------------------------------

CI_IMAGE_TAG ?= $(shell git rev-parse --abbrev-ref HEAD | tr '/' '-')
CI_IMAGE ?= quay.io/ansible/jewel-ci:$(CI_IMAGE_TAG)
CI_CONTAINERFILE = tools/generated/Containerfile.ci

## Build the CI container image (amd64 for GitHub Actions runners)
ci-image: $(SOURCES_STAMP) podman-preflight
	$(PODMAN) build --platform linux/amd64 -f $(CI_CONTAINERFILE) -t $(CI_IMAGE) .

## Build and push the CI container image (only from devel or stable-* branches)
ci-image-push: podman-preflight
	@BRANCH=$$(git rev-parse --abbrev-ref HEAD); \
	if [ "$$BRANCH" != "devel" ] && ! echo "$$BRANCH" | grep -qE '^stable-[0-9]+\.[0-9]+$$'; then \
		echo "Error: CI image can only be pushed from 'devel' or a 'stable-*' branch (current: $$BRANCH)."; \
		exit 1; \
	fi
	$(MAKE) ci-image
	@if [ -n "$(QUAY_USERNAME)" ] && [ -n "$(QUAY_PASSWORD)" ]; then \
		echo "$(QUAY_PASSWORD)" | $(PODMAN) login quay.io -u "$(QUAY_USERNAME)" --password-stdin || \
			{ echo "Error: Login to quay.io failed with provided QUAY_USERNAME/QUAY_PASSWORD."; exit 1; }; \
	fi; \
	$(PODMAN) push $(CI_IMAGE) || \
		{ echo ""; \
		  echo "Error: Push to quay.io failed. Possible causes:"; \
		  echo "  - Not logged in: run '$(PODMAN) login quay.io'"; \
		  echo "  - Expired credentials: re-run '$(PODMAN) login quay.io'"; \
		  echo "  - Repository does not exist: create 'ansible/jewel-ci' at quay.io"; \
		  echo "  - Insufficient permissions: ensure your account has write access"; \
		  echo ""; \
		  echo "Alternatively, export QUAY_USERNAME and QUAY_PASSWORD and re-run."; \
		  exit 1; }

# Hygiene
# --------------------------------------

## List open PRs and branches older than 6 months
hygiene-gh-old:
	./tools/scripts/github-hygiene.sh
