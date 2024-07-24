.PHONY: awx-up awx-up-check awx-down \
	dev-up dev-down \
	gateway-up gateway-up-check gateway-down \
	eda-server-up eda-server-down \
	smoke

ADMIN_PASSWORD := admin
SERVICE_DIR := ../services
GW_DIR := ..
AAP_DEV_DIR := .
# Taskfile for eda-server installs as task on some systems, but go-task for the dnf package
TASK_CMD ?= $(shell command -v task || command -v go-task)
# If you are running an old version, you might need docker-compose instead
DOCKER_COMPOSE?=docker compose

EDA_IMAGE_TAG?=aap-dev-eda
EDA_IMAGE_VERSION?=latest
# NOTE: see README.md on how to have git ignore the dev_hacked_settings.py file
EDA_ENV=EDA_IMAGE=$(EDA_IMAGE_TAG) EDA_IMAGE_VERSION=$(EDA_IMAGE_VERSION) EDA_ACTIVATION_WORKERS=1 EDA_DEFAULT_WORKERS=1 EDA_API_PORT=8010 DJANGO_SETTINGS_MODULE=aap_eda.settings.dev_hacked_settings
EDA_DOCKERFILE?=tools/docker/docker-compose-stage.yaml
EDA_REPO?=$(SERVICE_DIR)/eda-server
# NOTE: the container name depends on which Dockerfile you use, default is for stage
# for tools/docker/docker-compose-dev.yaml it is/was eda-eda-api-1
EDA_CONTAINER_NAME?=docker-eda-api-1

# If you over-ride the repo, make sure to NOT use a trailing slash, like AWX_REPO=~/repos/awx
AWX_REPO?=$(SERVICE_DIR)/awx


$(AWX_REPO)/.git/HEAD: ;
	cd $(SERVICE_DIR) && git clone https://github.com/ansible/awx.git

$(AWX_REPO)/tools/docker-compose/_sources/docker-compose.yml: $(AWX_REPO)/.git/HEAD
	cd $(AWX_REPO) && make docker-compose-sources COMPOSE_UP_OPTS=--detach EXTRA_SOURCES_ANSIBLE_OPTS="-e admin_password=$(ADMIN_PASSWORD)"

awx-up: $(AWX_REPO)/tools/docker-compose/_sources/docker-compose.yml
	$(DOCKER_COMPOSE) -f $(AWX_REPO)/tools/docker-compose/_sources/docker-compose.yml up --detach

awx-down: $(AWX_REPO)/tools/docker-compose/_sources/docker-compose.yml
	-$(DOCKER_COMPOSE) -f $(AWX_REPO)/tools/docker-compose/_sources/docker-compose.yml down

.awx-settings-hack:
	$(AAP_DEV_DIR)/awx-up-check.sh
	rm -rf /tmp/controller_settings.py
	python3 render_settings.py controller > /tmp/controller_settings.py
	docker cp /tmp/controller_settings.py tools_awx_1:/etc/tower/conf.d/controller_settings.py
	docker exec tools_awx_1 /bin/bash -c "supervisorctl restart tower-processes:awx-uwsgi"

gateway-up:
	cd $(GW_DIR) && make docker-compose COMPOSE_UP_OPTS=--detach ADMIN_PASSWORD=$(ADMIN_PASSWORD)

gateway-down:
	cd $(GW_DIR) && make docker-reset ADMIN_PASSWORD=$(ADMIN_PASSWORD)

$(EDA_REPO)/.git/HEAD: ;
	cd $(SERVICE_DIR) && git clone https://github.com/ansible/eda-server.git

/usr/local/bin/task:
	sh -c "$(curl --location https://taskfile.dev/install.sh)" -- -d -b /usr/local/bin/

.eda-server-change-password-hack:
	$(AAP_DEV_DIR)/eda-server-up-check.sh
	docker exec -it docker-eda-api-1 /app/venv/bin/python /app/src/src/aap_eda/manage.py shell -c 'from django.contrib.auth import get_user_model; u=get_user_model().objects.get(username="admin"); u.set_password("$(ADMIN_PASSWORD)"); u.save()'

$(EDA_REPO)/src/aap_eda/settings/dev_hacked_settings.py:
	python3 render_settings.py eda > $(EDA_REPO)/src/aap_eda/settings/dev_hacked_settings.py

# Explaining: the EDA go-task docker:build runs `docker compose build`, which respects EDA_IMAGE environment var
# this env var is referenced in the docker-compose yaml, so it obviously works in docker compose up too
eda-server-up: $(EDA_REPO)/.git/HEAD $(EDA_REPO)/src/aap_eda/settings/dev_hacked_settings.py
	echo "Using $(TASK_CMD)"
	cd $(EDA_REPO) && $(EDA_ENV) $(TASK_CMD) docker:build
	cd $(EDA_REPO) && $(EDA_ENV) $(DOCKER_COMPOSE) --file $(EDA_DOCKERFILE) up --detach --quiet-pull

eda-server-down: $(EDA_REPO)/.git/HEAD
	cd $(EDA_REPO) && $(EDA_ENV) $(DOCKER_COMPOSE) --file $(EDA_DOCKERFILE) down

dev-up: gateway-up awx-up eda-server-up .eda-server-change-password-hack
	$(AAP_DEV_DIR)/gateway-up-check.sh
	make .awx-settings-hack
	$(AAP_DEV_DIR)/awx-up-check.sh
	$(AAP_DEV_DIR)/eda-server-up-check.sh
	docker exec -it aap_gw_1 aap-gateway-manage migrate_service_data --api-slug=eda --username=admin --merge-organizations=true
	docker exec -it aap_gw_1 aap-gateway-manage migrate_service_data --api-slug=controller --username=admin  --merge-organizations=true

dev-down: awx-down gateway-down eda-server-down;

smoke:
	python3 $(AAP_DEV_DIR)/smoke.py
