.PHONY: awx-up awx-up-check awx-down \
	dev-up dev-down \
	gateway-up gateway-up-check gateway-down \
	eda-server-up eda-server-down \
	hub-server-up hup-server-down \
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
EDA_ENV=EDA_IMAGE=$(EDA_IMAGE_TAG) EDA_IMAGE_VERSION=$(EDA_IMAGE_VERSION) EDA_ACTIVATION_WORKERS=1 EDA_DEFAULT_WORKERS=1 EDA_API_PORT=8010 DJANGO_SETTINGS_MODULE=aap_eda.settings.dev_hacked_settings
# the eda-server docker-compose-stage.yaml file does not allow customizing setting module
EDA_DOCKERFILE?=tools/docker/docker-compose-dev.yaml
EDA_REPO?=$(SERVICE_DIR)/eda-server
# NOTE: the container name depends on which Dockerfile you use, default is for stage
# for tools/docker/docker-compose-dev.yaml it is/was eda-eda-api-1
EDA_CONTAINER_NAME?=docker-eda-api-1

HUB_CONTAINER_NAME?=galaxy_ng-api-1
HUB_REPO?=$(SERVICE_DIR)/galaxy_ng
HUB_DOCKERFILE=dev/compose/aap.yaml

# If you over-ride the repo, make sure to NOT use a trailing slash, like AWX_REPO=~/repos/awx
AWX_REPO?=$(SERVICE_DIR)/awx

## Display help targets
help:
	@printf "Available targets:\n"
	@$(MAKE) -s help/generate | grep -vE "\w(.PHONY)"

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

$(AWX_REPO)/.git/HEAD: ;
	cd $(SERVICE_DIR) && git clone https://github.com/ansible/awx.git

$(AWX_REPO)/tools/docker-compose/_sources/docker-compose.yml: $(AWX_REPO)/.git/HEAD
	cd $(AWX_REPO) && make docker-compose-sources COMPOSE_UP_OPTS=--detach EXTRA_SOURCES_ANSIBLE_OPTS="-e admin_password=$(ADMIN_PASSWORD)"

## Bring up AWX instance via docker-compose
awx-up: $(AWX_REPO)/tools/docker-compose/_sources/docker-compose.yml
	$(DOCKER_COMPOSE) -f $(AWX_REPO)/tools/docker-compose/_sources/docker-compose.yml up --detach

## Bring down AWX instance
awx-down: $(AWX_REPO)/tools/docker-compose/_sources/docker-compose.yml
	-$(DOCKER_COMPOSE) -f $(AWX_REPO)/tools/docker-compose/_sources/docker-compose.yml down

## Generate and copy over AWX related settings from template
.awx-settings-hack:
	$(AAP_DEV_DIR)/awx-up-check.sh
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

$(EDA_REPO)/.git/HEAD: ;
	cd $(SERVICE_DIR) && git clone https://github.com/ansible/eda-server.git

## Install task package
/usr/local/bin/task:
	sh -c "$(curl --location https://taskfile.dev/install.sh)" -- -d -b /usr/local/bin/

## Change admin password for running EDA instance
.eda-server-change-password-hack:
	$(AAP_DEV_DIR)/eda-server-up-check.sh
	docker exec -it docker-eda-api-1 /app/venv/bin/python /app/src/src/aap_eda/manage.py shell -c 'from django.contrib.auth import get_user_model; u=get_user_model().objects.get(username="admin"); u.set_password("$(ADMIN_PASSWORD)"); u.save()'

.eda-settings-hack:
	python3 render_settings.py eda > $(EDA_REPO)/src/aap_eda/settings/dev_hacked_settings.py

# Explaining: the EDA go-task docker:build runs `docker compose build`, which respects EDA_IMAGE environment var
# this env var is referenced in the docker-compose yaml, so it obviously works in docker compose up too
## Bring up EDA instance
eda-server-up: $(EDA_REPO)/.git/HEAD .eda-settings-hack
	echo "Using $(TASK_CMD)"
	cd $(EDA_REPO) && $(EDA_ENV) $(DOCKER_COMPOSE) --file $(EDA_DOCKERFILE) up --detach --quiet-pull

## Bring down EDA instance
eda-server-down: $(EDA_REPO)/.git/HEAD
	cd $(EDA_REPO) && $(EDA_ENV) $(DOCKER_COMPOSE) --file $(EDA_DOCKERFILE) down

# eda-server requires using a local image so you have to build that
dev-build:
	cd $(GW_DIR) && ADMIN_PASSWORD=$(ADMIN_PASSWORD) make docker-compose-build
	cd $(EDA_REPO) && $(EDA_ENV) DOCKER_COMPOSE="$(DOCKER_COMPOSE)" $(TASK_CMD) docker:build
	cd $(HUB_REPO) && $(DOCKER_COMPOSE) --file $(HUB_DOCKERFILE) build

## Bring up AAP services (Gateway + Controller + EDA) all at once
dev-up: gateway-up awx-up eda-server-up .eda-server-change-password-hack hub-server-up
	$(AAP_DEV_DIR)/gateway-up-check.sh
	make .awx-settings-hack
	make .hub-settings-hack
	$(AAP_DEV_DIR)/awx-up-check.sh
	$(AAP_DEV_DIR)/eda-server-up-check.sh
	docker exec -it aap_gw_1 aap-gateway-manage migrate_service_data --api-slug=controller --username=admin  --merge-organizations=true
	docker exec -it aap_gw_1 aap-gateway-manage migrate_service_data --api-slug=galaxy --username=admin --merge-organizations=true
	docker exec -it aap_gw_1 aap-gateway-manage migrate_service_data --api-slug=eda --username=admin --merge-organizations=true

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

hub-server-up: $(HUB_REPO)/.git/HEAD
	cd $(HUB_REPO) && $(DOCKER_COMPOSE) --file $(HUB_DOCKERFILE) up --build --detach --quiet-pull

.hub-settings-hack:
	$(AAP_DEV_DIR)/hub-up-check.sh
	rm -rf /tmp/hub_settings.py
	python3 render_settings.py galaxy > /tmp/hub_settings.py
	docker cp /tmp/hub_settings.py $(HUB_CONTAINER_NAME):/etc/pulp/settings.local.py

$(HUB_REPO)/.git/HEAD: ;
	cd $(SERVICE_DIR) && git clone https://github.com/ansible/galaxy_ng.git

hub-server-down:
	cd $(HUB_REPO) && $(DOCKER_COMPOSE) --file $(HUB_DOCKERFILE) down && docker volume rm var_lib_pulp


