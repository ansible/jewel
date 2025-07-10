SHELL=/bin/bash

# Prefer python 3.11 but take python3 if 3.11 is not installed
PYTHON := $(notdir $(shell for i in python3.11 python3; do command -v $$i; done|sed 1q))
CHECK_SYNTAX_FILES ?= aap_gateway_api/ aap-dev/ ansible_platform_collection/
RM ?= /bin/rm
UID := $(shell id -u)
TOX_ARGS ?= ""
DOCKER_COMPOSE ?= docker compose
COMPOSE_OPTS ?=
COMPOSE_UP_OPTS ?=
ADMIN_PASSWORD ?= $(shell $(PYTHON) -c "import secrets; print(secrets.token_urlsafe(20))")
GATEWAY_ABS_PATH := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
UNAME_S := $(shell uname -s)
ANSIBLE_CONFIG ?= tools/ansible/ansible.cfg
export ANSIBLE_CONFIG

.PHONY: PYTHON_VERSION clean git_hooks_config \
	check lint check_black check_flake8 check_isort \
	docker-compose plumb update_django_ansible_base_hash \
	collection-install collection-test collection-docs \
	collection-lint collection-sanity  collection-test-completeness \
        collection-test-integration-check

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

## Run linters (and modify files if necessary)
lint:
	tox -m lint

## Run black syntax check
check_black:
	tox -e black -- --check $(CHECK_SYNTAX_FILES)

## Run flake8 syntax check
check_flake8:
	tox -e flake8 -- $(CHECK_SYNTAX_FILES)

## Run isort syntax check
check_isort:
	tox -e isort -- --check $(CHECK_SYNTAX_FILES)

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

## prepare docker-compose-stage source files
docker-compose-stage-sources: tools/ansible/roles/sources/templates/docker-compose-stage.yml.j2 tools/generated/sources tools/generated/proxy.yml tools/generated/gateway.crt
## start docker-compose-stage pods
docker-compose-stage: docker-compose-stage-sources
	env UID=${UID} $(DOCKER_COMPOSE) -f tools/generated/docker-compose-stage.yml $(COMPOSE_OPTS) up --remove-orphans $(COMPOSE_UP_OPTS) &
## remove docker-compose-stage pods
docker-compose-stage-cleanup:
	if [ -f tools/generated/docker-compose-stage.yml ] ; then $(DOCKER_COMPOSE) -f tools/generated/docker-compose-stage.yml down -v ; fi
## Fetch service key
fetch-service-key:
	ansible-playbook tools/ansible/fetch-service-key.yml -e @container-startup.yml
## Migrate service data to services
migrate-service-data:
	ansible-playbook tools/ansible/migrate-service-data.yml -e @container-startup.yml

## Get migrate_service_data.py from stable-2.5 branch
./aap_gateway_api/management/commands/migrate_service_data_2.5.py:
	@echo "Finding github.com/ansible-automation-platform/aap-gateway remote..."
	@AAP_REMOTE=$$(git remote -v | grep 'github.com[:/]ansible-automation-platform/aap-gateway' | head -1 | awk '{print $$1}'); \
	if [ -z "$$AAP_REMOTE" ]; then \
		echo "Error: No remote found for github.com/ansible-automation-platform/aap-gateway"; \
		exit 1; \
	fi; \
	echo "Using remote: $$AAP_REMOTE"; \
	echo "Fetching from remote..."; \
	git fetch $$AAP_REMOTE; \
	echo "Extracting migrate_service_data.py from stable-2.5 branch..."; \
	git show $$AAP_REMOTE/stable-2.5:aap_gateway_api/management/commands/migrate_service_data.py > ./aap_gateway_api/management/commands/migrate_service_data_2.5.py; \
	echo "migrate_service_data_2.5.py created successfully"


## Start docker containers without additional playbooks
docker-compose-basic: tools/generated/sources docker-compose-build git_hooks_config
	env UID=${UID} $(DOCKER_COMPOSE) -f tools/generated/docker-compose.yml $(COMPOSE_OPTS) up --remove-orphans $(COMPOSE_UP_OPTS)

## Start the docker container + plumb the sidecar containers and register services' proxy
docker-compose: docker-compose-detached register-services plumb
	@if [[ ! "${COMPOSE_UP_OPTS}" =~ "-d" ]] ; then \
		env UID=${UID} $(DOCKER_COMPOSE) -f tools/generated/docker-compose.yml up --no-recreate; \
	fi

## Start the docker container in detached mode, wait for finish
docker-compose-detached: tools/generated/sources docker-compose-build git_hooks_config
	env DOCKER_COMPOSE="${DOCKER_COMPOSE}" ansible-playbook tools/ansible/initialize-containers.yml -e @container-startup.yml -e @tools/ansible/vars/container_config.yml;
	env UID=${UID} $(DOCKER_COMPOSE) -f tools/generated/docker-compose.yml $(COMPOSE_OPTS) up --remove-orphans $(COMPOSE_UP_OPTS) --wait;

## Attach to the container logs if docker in detached mode
docker-compose-attach: tools/generated/sources
	env UID=${UID} $(DOCKER_COMPOSE) -f tools/generated/docker-compose.yml up --no-recreate

## Delete the containers and docker networks and Remove all generated files when starting up docker
docker-reset: tools/generated/sources
	if [ -f tools/generated/docker-compose.yml ] ; then $(DOCKER_COMPOSE) -f tools/generated/docker-compose.yml down -v ; fi
	rm -fr tools/generated/{,.[!.],..?}*
	touch tools/generated/.gitkeep

## Remove the container volumes and docker networks
docker-reset-volumes: tools/generated/sources
	if [ -f tools/generated/docker-compose.yml ] ; then $(DOCKER_COMPOSE) -f tools/generated/docker-compose.yml down -v ; fi

## Generate the default container-startup.yml file
container-startup.yml: tools/configs/container-startup.yml
	@if [ -f container-startup.yml ] ; then \
		cp container-startup.yml container-startup.yml.backup; \
		echo ">>>>>> WARNING <<<<<<<<" ; \
		echo "container-startup.yml has been overwritten but a backup was taken (will be overwritten on next change)!"; \
	fi;
	@sed "s/gateway_admin_password: .*/gateway_admin_password: '$(ADMIN_PASSWORD)'/" tools/configs/container-startup.yml > ./container-startup.yml

## Generate the container-startup.yml from container-startup-podman.yml file
container-startup-podman.yml: tools/configs/container-startup-podman.yml
	@if [ -f container-startup.yml ] ; then \
		cp container-startup.yml container-startup.yml.backup; \
		echo ">>>>>> WARNING <<<<<<<<" ; \
		echo "container-startup.yml has been overwritten but a backup was taken (will be overwritten on next change)!"; \
	fi;
	@sed "s/gateway_admin_password: .*/gateway_admin_password: '$(ADMIN_PASSWORD)'/" tools/configs/container-startup-podman.yml > ./container-startup.yml

## Generate all files from generate-source playbook
tools/generated/sources: tools/ansible/roles/sources/templates/Dockerfile.j2 tools/ansible/roles/sources/templates/docker-compose.yml.j2 tools/ansible/roles/sources/templates/redis-users.acl.j2 container-startup.yml
	ansible-galaxy install -r requirements/requirements.yml
	ansible-playbook tools/ansible/generate-sources.yml \
	    -e @tools/ansible/vars/container_config.yml \
	    -e @container-startup.yml

## Build the docker containers
docker-compose-build: tools/generated/sources update_django_ansible_base_hash tools/generated/.has_built_api

API_TARGETS = tools/generated/.django_ansible_base_head tools/configs/uwsgi.ini tools/configs/supervisord.conf tools/generated/sources requirements/requirements.txt requirements/requirements_dev.txt tools/scripts/auto-reload tools/configs/nginx.conf tools/generated/gateway.crt tools/generated/proxy.yml $(shell find tools -type f -name "*gateway*") $(shell find tools/ansible -type f)
ifndef HEADLESS
    API_TARGETS += tools/generated/.has_built_ui
endif
## Build the API container
tools/generated/.has_built_api: $(API_TARGETS)
	mkdir -p django-ansible-base/requirements
	$(eval GATEWAY_NODE_COUNT=$(shell grep 'gateway_node_count' container-startup.yml | sed 's:[^0-9]::g')) \
	$(eval GATEWAY_NODES=$(shell seq 1 ${GATEWAY_NODE_COUNT} | sed 's:^:gateway:g' | xargs)) \
	$(DOCKER_COMPOSE) -f tools/generated/docker-compose.yml \
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
		echo local > tools/generated/.django_ansible_base_head; \
	fi

## Generate the tools/generated/.django_ansible_base_head file for tracking django-ansible-base
tools/generated/.django_ansible_base_head: update_django_ansible_base_hash

## Check to pull the latest platform-ui if needed
tools/generated/.has_built_ui:
	docker pull quay.io/ansible/platform-ui:latest > tools/generated/last_ui_pull
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
tools/generated/proxy.yml: $(shell find tools/ansible/roles/proxy-config/templates -type f)
	ansible-playbook tools/ansible/generate-proxy-configs.yml -e @tools/ansible/vars/container_config.yml -e @container-startup.yml

## Build the requirements.txt file
requirements/requirements.txt: requirements/requirements.in
	cd requirements && \
	    ./updater.sh run
	@-cd .. || true

## Register services and ports
register-services: tools/generated/proxy.yml collection-install
	ansible-playbook tools/ansible/register-services.yml -e @container-startup.yml -e @tools/generated/proxy.yml

## Remove the services and ports generated from the register-services target
cleanup-services: tools/generated/proxy.yml collection-install
	ansible-playbook tools/ansible/register-services.yml -e @container-startup.yml -e @tools/generated/proxy.yml -e gateway_state=absent

## Plumb the sidecar containers
plumb:
	ansible-playbook tools/ansible/plumb.yml -e @tools/ansible/vars/container_config.yml -e @container-startup.yml

## Install the collection locally on your machine
collection-install:
	ansible-galaxy collection install ansible_platform_collection --force

## Run the collection tests
collection-test: collection-install
	$(eval ADMIN_PW=$(shell awk '/gateway_admin_password/{print $$2}' container-startup.yml | xargs echo))
	echo 'gateway_password: $(ADMIN_PW)' > \
	  /tmp/collections/ansible_collections/ansible/platform/tests/integration/integration_config.yml
	cd /tmp/collections/ansible_collections/ansible/platform && \
	  ansible-test integration --venv --requirements --coverage

## Run the collection sanity tests
collection-sanity: collection-install
	cd /tmp/collections/ansible_collections/ansible/platform && \
	ansible-test sanity

## Run the collections test-integration check to see if all modules have integration tests
collection-test-integration-check:
	./ansible_platform_collection/tests/test_integration_check.py

## Run the collections test-completness check
collection-test-completeness:
	./ansible_platform_collection/tests/test_completeness.py

## Run the collections docs check
collection-docs: collection-install
	@RC=0 ; \
	for file_name in $$(ls ansible_platform_collection/plugins/modules/*.py) ; do \
            module=$$(echo $${file_name} | sed 's:^.*/::' | sed 's:\..*::') ; \
            ansible-doc -M ansible_platform_collection/plugins/modules $${module} 1> /dev/null ; \
            RC=$$(( RC + $$? )) ; \
	done ; \
	for file_name in $$(ls ansible_platform_collection/plugins/lookup/*.py) ; do \
            module=$$(echo $${file_name} | sed 's:^.*/::' | sed 's:\..*::') ; \
            ansible-doc -M ansible_platform_collection/plugins/lookup -t lookup $${module} 1> /dev/null ; \
            RC=$$(( RC + $$? )) ; \
	done ; \
	if [[ $$RC -eq 0 ]] ; then echo "Doc Passed" ; else echo "Docs Failed" ; fi ; \
	exit $$RC

## Run the collection lint check
collection-lint: collection-install
	# ansible-lint gets its settings from ansible_platform_collection/.ansible-lint
	cd ansible_platform_collection && ansible-lint



# Hygiene
# --------------------------------------

## List open PRs and branches older than 6 months
hygiene-gh-old:
	./tools/scripts/github-hygiene.sh
