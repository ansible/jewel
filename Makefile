SHELL=/bin/bash

# Prefer python 3.11 but take python3 if 3.11 is not installed
PYTHON := $(notdir $(shell for i in python3.11 python3; do command -v $$i; done|sed 1q))
CHECK_SYNTAX_FILES ?= .
RM ?= /bin/rm
SERVICE_LIB_DIR ?= service_lib
SERVICE_LIB_DIST ?= $(SERVICE_LIB_DIR)/dist
UID := $(shell id -u)
TOX_ARGS ?= ""
COMPOSE_OPTS ?=
COMPOSE_UP_OPTS ?=

.PHONY: PYTHON_VERSION clean \
	check lint check_black check_flake8 check_isort \
	build_service_lib test_service_lib \
	docker-compose plumb update_django_ansible_base_hash

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
docker-compose: tools/generated/docker-compose.yml docker-compose-build .git/hooks/pre-commit
	ansible-playbook tools/ansible/initialize-containers.yml -e @container-startup.yml -e @tools/ansible/vars/container_config.yml;
	env UID=${UID} docker-compose -f tools/generated/docker-compose.yml $(COMPOSE_OPTS) up --remove-orphans $(COMPOSE_UP_OPTS)

## Generate the default container-startup.yml file
container-startup.yml: tools/configs/container-startup.yml
	cp tools/configs/container-startup.yml ./container-startup.yml

## Generate the docker-compose.yml file
tools/generated/docker-compose.yml: container-startup.yml tools/ansible/roles/sources/templates/docker-compose.yml.j2
	ansible-playbook tools/ansible/generate-docker-compose.yml -e @tools/ansible/vars/container_config.yml -e @container-startup.yml

## Build the docker containers
docker-compose-build: tools/generated/docker-compose.yml update_django_ansible_base_hash tools/generated/.has_built_api tools/generated/.has_built_ui

## Build the API container
tools/generated/.has_built_api: tools/generated/.django_ansible_base_head tools/generated/.has_built_ui tools/configs/uwsgi.ini tools/configs/supervisord.conf tools/docker/Dockerfile.gateway requirements/requirements.txt requirements/requirements_dev.txt tools/scripts/auto-reload tools/configs/nginx.conf tools/generated/gateway.crt tools/generated/proxy.yml $(shell find tools -type f -name "*gateway*") $(shell find tools/ansible -type f)
	mkdir -p django-ansible-base
	docker-compose -f tools/generated/docker-compose.yml \
	    build \
	    --build-arg DJANGO_ANSIBLE_BASE_DEVEL_SHA=$(shell cat tools/generated/.django_ansible_base_head) \
	    gateway
	touch $@

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
	fi

tools/generated/.django_ansible_base_head: update_django_ansible_base_hash

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

## Build the proxy config file
tools/generated/proxy.yml:
	cp tools/configs/proxy-config-sample.yml tools/generated/proxy.yml

## Build the requirements.txt file
requirements/requirements.txt: requirements/requirements.in
	cd requirements && \
	    ./updater.sh run
	@-cd .. || true

## Plumb the sidecar containers
plumb:
	ansible-playbook tools/ansible/plumb.yml -e @tools/ansible/vars/container_config.yml -e @container-startup.yml

## Remove all generated files when starting up docker
docker-reset: tools/generated/docker-compose.yml
	if [ -f tools/generated/docker-compose.yml ] ; then docker-compose -f tools/generated/docker-compose.yml down -v ; fi
	rm -fr tools/generated/{,.[!.],..?}*
	touch tools/generated/.gitkeep

## Remove the container volumes
docker-reset-volumes: tools/generated/docker-compose.yml
	if [ -f tools/generated/docker-compose.yml ] ; then docker-compose -f tools/generated/docker-compose.yml down -v ; fi
