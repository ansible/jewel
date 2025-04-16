.PHONY: awx-up awx-up-check awx-down \
	dev-up dev-down \
	gateway-up gateway-up-check gateway-down \
	eda-server-up eda-server-down \
	hub-server-up hub-server-down \
	disconnect-service-mesh-network \
	smoke help help/generate .awx-settings-hack .eda-settings-hack .hub-settings-hack

ADMIN_PASSWORD := admin
SERVICE_DIR := ../services
GW_DIR := ..
AAP_DEV_DIR := .
# Taskfile for eda-server installs as task on some systems, but go-task for the dnf package
TASK_CMD ?= $(shell command -v task || command -v go-task)
# If you are running an old version, you might need docker-compose instead
DOCKER_COMPOSE?=docker compose

# this is the default eda-server image, which maybe you already have built
EDA_IMAGE_TAG?=localhost/aap-eda
EDA_IMAGE_VERSION?=latest
# NOTE: see README.md on how to have git ignore the dev_hacked_settings.py file
EDA_ENV=EDA_IMAGE=$(EDA_IMAGE_TAG) EDA_IMAGE_VERSION=$(EDA_IMAGE_VERSION) EDA_ACTIVATION_WORKERS=1 EDA_DEFAULT_WORKERS=1 EDA_API_PORT=8010 EDA_REDIS_PORT=6389 EDA_MODE=testing
# the eda-server docker-compose-stage.yaml file does not allow customizing setting module
EDA_DOCKERFILE?=tools/docker/docker-compose-dev.yaml
EDA_REPO?=$(SERVICE_DIR)/eda-server
# NOTE: the container name depends on which Dockerfile you use, default is for stage
# for tools/docker/docker-compose-dev.yaml it is/was eda-eda-api-1
EDA_CONTAINER_NAME?=docker-eda-api-1

HUB_PROJECT_NAME?=galaxy_ng
HUB_CONTAINER_NAME?=$(HUB_PROJECT_NAME)-api-1
HUB_REPO?=$(SERVICE_DIR)/galaxy_ng
HUB_DOCKERFILE=dev/compose/aap.yaml

# If you over-ride the repo, make sure to NOT use a trailing slash, like AWX_REPO=~/repos/awx
AWX_REPO?=$(SERVICE_DIR)/awx
LIGHTSPEED_REPO?=$(SERVICE_DIR)/ansible-ai-connect-service
LIGHTSPEED_ENV=DJANGO_SETTINGS_MODULE=ansible_ai_connect.main.settings.aap_dev_hacked_settings LIGHTSPEED_PORT=7080

## Display help targets
help:
	@printf "Available targets:\n"
	@$(MAKE) -s help/generate | grep -vE "\w(.PHONY)"

## Generate help output from MAKEFILE_LIST
help/generate:
	@awk '/^[-a-zA-Z_0-9%:\\\.\/\(\)$$]+:/ { \
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

## Clone the AWX repo if not already there
$(AWX_REPO)/.git/HEAD: ;
	cd $(SERVICE_DIR) && git clone https://github.com/ansible/awx.git

## Generate AWX docker-compose.yml file
$(AWX_REPO)/tools/docker-compose/_sources/docker-compose.yml: $(AWX_REPO)/.git/HEAD
	cd $(AWX_REPO) && make docker-compose-sources COMPOSE_UP_OPTS=--detach EXTRA_SOURCES_ANSIBLE_OPTS="-e admin_password=$(ADMIN_PASSWORD)"

## Bring up AWX instance via docker-compose
awx-up:
	if [[ "$(AWX_REPO)" == "skip" ]]; then \
		echo "Skipping AWX server start" ; \
	else \
		make $(AWX_REPO)/tools/docker-compose/_sources/docker-compose.yml; \
		$(DOCKER_COMPOSE) -f $(AWX_REPO)/tools/docker-compose/_sources/docker-compose.yml up --detach ; \
	fi;

## Bring down AWX instance
awx-down: $(AWX_REPO)/tools/docker-compose/_sources/docker-compose.yml
	-$(DOCKER_COMPOSE) -f $(AWX_REPO)/tools/docker-compose/_sources/docker-compose.yml down

## Generate and copy over AWX related settings from template
.awx-settings-hack:
	rm -rf /tmp/controller_settings.py
	python3 render_settings.py controller > /tmp/controller_settings.py
	docker cp /tmp/controller_settings.py tools_awx_1:/etc/tower/conf.d/controller_settings.py
	docker exec tools_awx_1 /bin/bash -c "supervisorctl restart tower-processes:awx-uwsgi"

## Bring up Gateway instance
gateway-up:
	cd $(GW_DIR) && make docker-compose COMPOSE_UP_OPTS=--detach ADMIN_PASSWORD=$(ADMIN_PASSWORD)

## Bring down Gateway instance
gateway-down:
	cd $(GW_DIR) && make docker-reset ADMIN_PASSWORD=$(ADMIN_PASSWORD)

## Clone the eda-server repo if not already there
$(EDA_REPO)/.git/HEAD: ;
	cd $(SERVICE_DIR) && git clone https://github.com/ansible/eda-server.git

## Install task package
/usr/local/bin/task:
	sh -c "$(curl --location https://taskfile.dev/install.sh)" -- -d -b /usr/local/bin/

## Change admin password for running EDA instance
.eda-server-change-password-hack:
	if [[ "$(EDA_REPO)" == "skip" ]]; then \
		echo "Skipping EDA password change hack" ; \
	else \
		$(AAP_DEV_DIR)/eda-server-up-check.sh ; \
		docker exec -it docker-eda-api-1 /app/venv/bin/python /app/src/src/aap_eda/manage.py shell -c 'from django.contrib.auth import get_user_model; u=get_user_model().objects.get(username="admin"); u.set_password("$(ADMIN_PASSWORD)"); u.save()' ; \
	fi;

## Generate dynamic EDA settings and put in source tree
.eda-settings-hack:
	python3 render_settings.py eda > $(EDA_REPO)/src/aap_eda/settings/testing_defaults.py

# Explaining: the EDA go-task docker:build runs `docker compose build`, which respects EDA_IMAGE environment var
# this env var is referenced in the docker-compose yaml, so it obviously works in docker compose up too
## Bring up EDA instance
eda-server-up:
	if [[ "$(EDA_REPO)" == "skip" ]]; then \
		echo "Skipping EDA server start" ; \
	else \
		make $(EDA_REPO)/.git/HEAD ; \
		make .eda-settings-hack ; \
		echo "Using $(TASK_CMD)" ; \
		cd $(EDA_REPO) && $(EDA_ENV) $(DOCKER_COMPOSE) --file $(EDA_DOCKERFILE) up --detach --quiet-pull ; \
	fi;

## Bring down EDA instance
eda-server-down: $(EDA_REPO)/.git/HEAD
	cd $(EDA_REPO) && $(EDA_ENV) $(DOCKER_COMPOSE) --file $(EDA_DOCKERFILE) down

## Build local images for EDA, Gateway, and Hub
dev-build:
	cd $(GW_DIR) && ADMIN_PASSWORD=$(ADMIN_PASSWORD) make docker-compose-build
	if [[ "$(EDA_REPO)" != "skip" ]]; then make $(EDA_REPO)/.git/HEAD && cd $(EDA_REPO) && $(EDA_ENV) DOCKER_COMPOSE="$(DOCKER_COMPOSE)" $(TASK_CMD) docker:build ; fi
	if [[ "$(HUB_REPO)" != "skip" ]]; then make $(HUB_REPO)/.git/HEAD && cd $(HUB_REPO) && USER_ID=$(shell id -u) $(DOCKER_COMPOSE) --file $(HUB_DOCKERFILE) build ; fi

## Bring up AAP services (Gateway + Controller + EDA) all at once
dev-up: gateway-up awx-up eda-server-up .eda-server-change-password-hack hub-server-up
	$(AAP_DEV_DIR)/aap-service-cluster-up-check.sh gateway gateway/v1/
	if [[ "$(AWX_REPO)" == "skip" ]]; then \
		echo "Skipping controller actions" ; \
	else \
		make .awx-settings-hack ; \
		$(AAP_DEV_DIR)/aap-service-cluster-up-check.sh controller controller/v2/ping/ ; \
		docker exec -it aap_gw_1 aap-gateway-manage migrate_service_data --api-slug=controller --username=admin  --merge-organizations=true ; \
	fi;
	if [[ "$(EDA_REPO)" == "skip" ]]; then \
		echo "Skipping EDA server actions" ; \
	else \
		$(AAP_DEV_DIR)/aap-service-cluster-up-check.sh EDA eda/v1/status/ ; \
		docker exec -it aap_gw_1 aap-gateway-manage migrate_service_data --api-slug=eda --username=admin --merge-organizations=true ; \
	fi;
	if [[ "$(HUB_REPO)" == "skip" ]]; then \
		echo "Skipping Hub actions" ; \
	else \
		make .hub-settings-hack ; \
		$(AAP_DEV_DIR)/aap-service-cluster-up-check.sh hub galaxy/pulp/api/v3/status/ ; \
		docker exec -it aap_gw_1 aap-gateway-manage migrate_service_data --api-slug=galaxy --username=admin --merge-organizations=true ; \
	fi;

## Remove all running containers from "service-mesh" network
disconnect-service-mesh-network:
	$(shell for c in $$(docker network inspect -f '{{ range $$key, $$value := .Containers }}{{ printf "%s\n" .Name }}{{ end }}' service-mesh); do docker network disconnect service-mesh $$c; done)

## Bring down all AAP services
dev-down: disconnect-service-mesh-network awx-down gateway-down eda-server-down hub-server-down;

## Run smoke tests
smoke:
	python3 $(AAP_DEV_DIR)/smoke.py

#######################################################
#	HUB
#######################################################

## Bring up the Hub server
hub-server-up:
	if [[ "$(HUB_REPO)" == "skip" ]]; then \
		echo "Skipping Hub server start" ; \
	else \
		make $(HUB_REPO)/.git/HEAD ; \
		cd $(HUB_REPO) && USER_ID=$(shell id -u) DOCKER_BUILDKIT=0 $(DOCKER_COMPOSE) --file $(HUB_DOCKERFILE) --project-name $(HUB_PROJECT_NAME) up --build --detach --quiet-pull ; \
	fi;

## Generate dynamic hub settings and copy into running container
.hub-settings-hack:
	$(AAP_DEV_DIR)/hub-up-check.sh ; \
	rm -rf /tmp/hub_settings.py ; \
	python3 render_settings.py galaxy > /tmp/hub_settings.py ; \
	docker cp /tmp/hub_settings.py $(HUB_CONTAINER_NAME):/etc/pulp/settings.local.py ; \

## Clone the galaxy_ng repo if not already there
$(HUB_REPO)/.git/HEAD: ;
	cd $(SERVICE_DIR) && git clone https://github.com/ansible/galaxy_ng.git

## Bring down the Hub server
hub-server-down:
	cd $(HUB_REPO) && $(DOCKER_COMPOSE) --file $(HUB_DOCKERFILE) --project-name $(HUB_PROJECT_NAME) down && docker volume rm var_lib_pulp

lightspeed-settings-hack:
	python3 render_settings.py lightspeed > $(LIGHTSPEED_REPO)/ansible_ai_connect/main/settings/aap_dev_hacked_settings.py

lightspeed-up: lightspeed-settings-hack
	cd $(LIGHTSPEED_REPO) && $(LIGHTSPEED_ENV) $(DOCKER_COMPOSE) -f tools/docker-compose/compose.yaml --env-file ./.env up --remove-orphans

lightspeed-down:
	cd $(LIGHTSPEED_REPO) && $(LIGHTSPEED_ENV) $(DOCKER_COMPOSE) -f tools/docker-compose/compose.yaml --env-file ./.env down
