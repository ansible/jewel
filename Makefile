SHELL=/bin/bash

# Prefer python 3.11 but take python3 if 3.11 is not installed
PYTHON := $(notdir $(shell for i in python3.11 python3; do command -v $$i; done|sed 1q))
CHECK_SYNTAX_FILES ?= .
RM ?= /bin/rm
SERVICE_LIB_DIR ?= service_lib
SERVICE_LIB_DIST ?= $(SERVICE_LIB_DIR)/dist
UID := $(shell id -u)
TOX_ARGS ?= ""

.PHONY: PYTHON_VERSION clean \
	check_black check_flake8 check_isort \
	build_service_lib test_service_lib \
	docker-compose plumb

PYTHON_VERSION:
	@echo "$(subst python,,$(PYTHON))"

## Install the pre-commit hook in the approprate .git directory structure
.git/hooks/pre-commit:
	@echo "if [ -x pre-commit.sh ]; then" > .git/hooks/pre-commit
	@echo "    ./pre-commit.sh;" >> .git/hooks/pre-commit
	@echo "fi" >> .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit

## Zero out all of the temp and build files
clean:
	@-find . -type f -regex ".*\.py[co]$$" -print0 | xargs -0 $(RM) -f
	@-find . -type d -name "__pycache__" -print0 \
			 -o -type d -name ".pytest_cache" -print0 | xargs -0 $(RM) -rf
	@-$(RM) --preserve-root=all -rf $(SERVICE_LIB_DIST)/* || $(RM) -rf $(SERVICE_LIB_DIST)/*

# Test targets
# -------------------------------------

## Run black syntax check
check_black:
	black --check $(CHECK_SYNTAX_FILES)

## Run flake8 syntax check
check_flake8:
	flake8 $(CHECK_SYNTAX_FILES)

## Run isort syntax check
check_isort:
	isort --check $(CHECK_SYNTAX_FILES)


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

## Start the docker container
docker-compose: tools/generated/docker-compose.yaml docker-compose-build .git/hooks/pre-commit
	ansible-playbook tools/ansible/initialize-containers.yml -e @container-startup.yml -e @tools/ansible/vars/container_config.yml;
	env UID=${UID} docker-compose -f tools/generated/docker-compose.yaml up --remove-orphans

## Generate the default container-startup.yml file
container-startup.yml: tools/configs/container-startup.yml
	cp tools/configs/container-startup.yml ./container-startup.yml

## Generate the docker-compoe.yaml file
tools/generated/docker-compose.yaml: container-startup.yml tools/ansible/roles/sources/templates/docker-compose.yml.j2
	ansible-playbook tools/ansible/generate-docker-compose.yml -e @tools/ansible/vars/container_config.yml -e @container-startup.yml

## Build the docker containers
docker-compose-build: tools/generated/.has_built_api tools/generated/.has_built_proxy

## Build the API container
tools/generated/.has_built_api: tools/configs/uwsgi.ini tools/configs/supervisord.conf tools/docker/Dockerfile.gateway requirements/requirements.txt tools/scripts/auto-reload tools/configs/nginx.conf tools/generated/gateway.crt $(shell find tools -type f -name "*gateway*") $(shell find tools/ansible -type f)
	docker-compose -f tools/generated/docker-compose.yaml build gateway
	touch $@

## Build the proxy container
tools/generated/.has_built_proxy: tools/docker/Dockerfile.proxy tools/generated/gateway.crt tools/generated/proxy.yaml $(shell find tools -type f -name "*envoy*") $(shell find tools/ansible -type f)
	docker-compose -f tools/generated/docker-compose.yaml build proxy
	touch $@

## Build the cert file
tools/generated/gateway.crt:
	openssl req -nodes -newkey rsa:2048 -keyout tools/generated/gateway.key -out tools/generated/gateway.csr -subj "/C=US/ST=North Carolina/L=Durham/O=Ansible/OU=Gateway Development/CN=localhost"
	openssl x509 -req -days 365 -in tools/generated/gateway.csr -signkey tools/generated/gateway.key -out tools/generated/gateway.crt

## Build the proxy config file
tools/generated/proxy.yaml:
	cp tools/configs/proxy-config-sample.yaml tools/generated/proxy.yaml

## Build the requirements.txt file
requirements/requirements.txt: requirements/requirements.in
	cd requirements && \
	    ./updater.sh run
	@-cd .. || true

## Plumb the sidecar containers
plumb:
	ansible-playbook tools/ansible/plumb.yml -e @container-startup.yml -e @tools/ansible/vars/container_config.yml
