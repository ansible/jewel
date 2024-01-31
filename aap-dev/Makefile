.PHONY: awx-up awx-up-check awx-down \
	dev-up dev-down \
	gateway-up gateway-up-check gateway-down \
	smoke

ADMIN_PASSWORD := admin
SERVICE_DIR := ../services
GW_DIR := ../
AAP_DEV_DIR := .

$(SERVICE_DIR)/awx/.git/HEAD: ;
	cd $(SERVICE_DIR) && git clone https://github.com/ansible/awx.git

$(SERVICE_DIR)/awx/tools/docker-compose/_sources/docker-compose.yml: $(SERVICE_DIR)/awx/.git/HEAD
	cd $(SERVICE_DIR)/awx && make docker-compose COMPOSE_UP_OPTS=--detach EXTRA_SOURCES_ANSIBLE_OPTS="-e admin_password=$(ADMIN_PASSWORD)"

awx-up: $(SERVICE_DIR)/awx/tools/docker-compose/_sources/docker-compose.yml
	docker-compose -f $(SERVICE_DIR)/awx/tools/docker-compose/_sources/docker-compose.yml up --detach

awx-down: $(SERVICE_DIR)/awx/tools/docker-compose/_sources/docker-compose.yml
	-docker-compose -f $(SERVICE_DIR)/awx/tools/docker-compose/_sources/docker-compose.yml down

.awx-settings-hack:
	$(AAP_DEV_DIR)/awx-up-check.sh
	docker cp $(AAP_DEV_DIR)/controller_settings.py tools_awx_1:/etc/tower/conf.d/controller_settings.py
	docker exec tools_awx_1 /bin/bash -c "supervisorctl restart tower-processes:awx-uwsgi"

gateway-up:
	cd $(GW_DIR) && make docker-compose COMPOSE_UP_OPTS=--detach ADMIN_PASSWORD=$(ADMIN_PASSWORD)

gateway-down:
	cd $(GW_DIR) && make docker-reset

dev-up: gateway-up awx-up .awx-settings-hack
	$(AAP_DEV_DIR)/gateway-up-check.sh
	$(AAP_DEV_DIR)/awx-up-check.sh

dev-down: awx-down gateway-down ;

smoke:
	python3 $(AAP_DEV_DIR)/smoke.py
