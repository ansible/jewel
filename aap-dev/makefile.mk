.PHONY: awx-up awx-up-check \
	dev-up dev-down \
	gateway-up gateway-up-check \
	smoke

ADMIN_PASSWORD := admin

awx/.git/HEAD: ;
	git clone https://github.com/ansible/awx.git

awx/tools/docker-compose/_sources/docker-compose.yml: awx/.git/HEAD
	cd awx; make docker-compose COMPOSE_UP_OPTS=--detach EXTRA_SOURCES_ANSIBLE_OPTS="-e admin_password=$(ADMIN_PASSWORD)"

awx-up: awx/tools/docker-compose/_sources/docker-compose.yml
	docker-compose -f awx/tools/docker-compose/_sources/docker-compose.yml up --detach

awx-down: awx/tools/docker-compose/_sources/docker-compose.yml
	-docker-compose -f awx/tools/docker-compose/_sources/docker-compose.yml down

.awx-settings-hack:
	aap-dev/awx-up-check.sh
	docker cp aap-dev/controller_settings.py tools_awx_1:/etc/tower/conf.d/controller_settings.py
	docker exec tools_awx_1 /bin/bash -c "supervisorctl restart tower-processes:awx-uwsgi"

.awx-settings: .awx-settings-hack ;

gateway-up: COMPOSE_UP_OPTS = --detach
gateway-up: docker-compose

gateway-down: tools/generated/docker-compose.yml
	-docker-compose -f tools/generated/docker-compose.yml down

dev-up: gateway-up awx-up .awx-settings
	aap-dev/gateway-up-check.sh
	aap-dev/awx-up-check.sh

dev-down: awx-down gateway-down ;

smoke:
	python3 aap-dev/smoke.py
