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
	docker-compose

PYTHON_VERSION:
	@echo "$(subst python,,$(PYTHON))"

# Install the pre-commit hook in the approprate .git directory structure
.git/hooks/pre-commit:
	@echo "if [ -x pre-commit.sh ]; then" > .git/hooks/pre-commit
	@echo "    ./pre-commit.sh;" >> .git/hooks/pre-commit
	@echo "fi" >> .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit

# Zero out all of the temp and build files
clean:
	@-find . -type f -regex ".*\.py[co]$$" -print0 | xargs -0 $(RM) -f
	@-find . -type d -name "__pycache__" -print0 \
			 -o -type d -name ".pytest_cache" -print0 | xargs -0 $(RM) -rf
	@-$(RM) --preserve-root=all -rf $(SERVICE_LIB_DIST)/* || $(RM) -rf $(SERVICE_LIB_DIST)/*

# Test targets
# -------------------------------------

# Run black syntax check
check_black:
	black --check $(CHECK_SYNTAX_FILES)

# Run flake8 syntax check
check_flake8:
	flake8 $(CHECK_SYNTAX_FILES)

# Run isort syntax check
check_isort:
	isort --check $(CHECK_SYNTAX_FILES)

# Run service_lib tests
test_service_lib:
	cd service_lib; tox run ${TOX_ARGS}

check: check_black check_flake8 check_isort

# Build targets
# --------------------------------------

# Build the service_lib library into service_lib/dist
build_service_lib:
	python -m build service_lib

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

docker-compose: docker-compose-build
	env UID=${UID} docker-compose -f tools/docker/docker-compose.yaml up --remove-orphans

docker-compose-build: .has_built_api .has_built_proxy

.has_built_api: tools/configs/uwsgi.ini tools/configs/supervisord.conf tools/docker/Dockerfile requirements/requirements.txt tools/scripts/auto-reload tools/configs/nginx.conf tools/configs/gateway.crt $(shell find tools -type f -name "*gateway*")
	docker-compose -f tools/docker/docker-compose.yaml build gateway
	touch $@

.has_built_proxy: tools/docker/envoy.Dockerfile tools/configs/gateway.crt tools/configs/proxy.yaml $(shell find tools -type f -name "*envoy*")
	docker-compose -f tools/docker/docker-compose.yaml build proxy
	touch $@

tools/configs/gateway.crt:
	openssl req -nodes -newkey rsa:2048 -keyout tools/configs/gateway.key -out tools/configs/gateway.csr -subj "/C=US/ST=North Carolina/L=Durham/O=Ansible/OU=AWX Development/CN=awx.localhost"
	openssl x509 -req -days 365 -in tools/configs/gateway.csr -signkey tools/configs/gateway.key -out tools/configs/gateway.crt

tools/configs/proxy.yaml:
	cp tools/configs/proxy-config-sample.yaml tools/configs/proxy.yaml

requirements/requirements.txt: requirements/requirements.in
	cd requirements && \
	    ./updater.sh run
	@-cd .. || true

# Use the following proxy.yaml settings to use this server:
#   hub:
#     use_tls: true
#     proxy_root: /api/hub/
#     service_root: /api/galaxy/

#     load_balance:
#       - address: "localhost"
#         port: 5043
example/hub:
	docker build . -f tools/docker/hub.Dockerfile -t aap-gateway-hub
	docker run --rm --add-host=localhost:host-gateway -p 5043:443 --rm aap-gateway-hub
