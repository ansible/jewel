.PHONY: awx-up awx-up-check awx-down \
	dev-up dev-down \
	gateway-up gateway-up-check gateway-down \
	eda-server-up eda-server-down \
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

$(GW_DIR)/tools/generated/proxy.yml:
	$(AAP_DEV_DIR)/gateway-eda_server-config-hack.py $(GW_DIR)/tools/configs/proxy-config-sample.yml $(GW_DIR)/tools/generated/proxy.yml

.awx-settings-hack:
	$(AAP_DEV_DIR)/awx-up-check.sh
	docker cp $(AAP_DEV_DIR)/controller_settings.py tools_awx_1:/etc/tower/conf.d/controller_settings.py
	docker exec tools_awx_1 /bin/bash -c "supervisorctl restart tower-processes:awx-uwsgi"

gateway-up: $(GW_DIR)/tools/generated/proxy.yml
	cd $(GW_DIR) && make docker-compose COMPOSE_UP_OPTS=--detach ADMIN_PASSWORD=$(ADMIN_PASSWORD)

gateway-down:
	cd $(GW_DIR) && make docker-reset ADMIN_PASSWORD=$(ADMIN_PASSWORD)

$(SERVICE_DIR)/eda-server/.git/HEAD: ;
	cd $(SERVICE_DIR) && git clone https://github.com/ansible/eda-server.git

/usr/local/bin/task:
	sh -c "$(curl --location https://taskfile.dev/install.sh)" -- -d -b /usr/local/bin/

.eda-server-change-password-hack:
	$(AAP_DEV_DIR)/eda-server-up-check.sh
	docker exec -it eda_eda-api_1 /app/venv/bin/python /app/src/src/aap_eda/manage.py shell -c 'from django.contrib.auth import get_user_model; u=get_user_model().objects.get(username="admin"); u.set_password("$(ADMIN_PASSWORD)"); u.save()'

$(SERVICE_DIR)/eda-server/src/aap_eda/settings/eda_server_settings.py:
	cp $(AAP_DEV_DIR)/eda_server_settings.py $(SERVICE_DIR)/eda-server/src/aap_eda/settings/eda_server_settings.py

eda-server-up: $(SERVICE_DIR)/eda-server/.git/HEAD $(SERVICE_DIR)/eda-server/src/aap_eda/settings/eda_server_settings.py
	cd $(SERVICE_DIR)/eda-server && task docker:build
	cd $(SERVICE_DIR)/eda-server && EDA_API_PORT=8010 DJANGO_SETTINGS_MODULE=aap_eda.settings.eda_server_settings task docker:up

eda-server-down: $(SERVICE_DIR)/eda-server/.git/HEAD
	cd $(SERVICE_DIR)/eda-server && task docker:down

dev-up: gateway-up awx-up .awx-settings-hack eda-server-up .eda-server-change-password-hack
	$(AAP_DEV_DIR)/gateway-up-check.sh
	$(AAP_DEV_DIR)/awx-up-check.sh
	$(AAP_DEV_DIR)/eda-server-up-check.sh

dev-down: awx-down gateway-down eda-server-down;

smoke:
	python3 $(AAP_DEV_DIR)/smoke.py
