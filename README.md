[![Quality Gate Status](https://sonarqube.corp.redhat.com/api/project_badges/measure?project=ansible_aap-gateway&metric=alert_status&token=sqb_19096b3174c8d45029973fd724f27e21efc6b025)](https://sonarqube.corp.redhat.com/dashboard?id=ansible_aap-gateway)
[![Coverage](https://sonarqube.corp.redhat.com/api/project_badges/measure?project=ansible_aap-gateway&metric=coverage&token=sqb_19096b3174c8d45029973fd724f27e21efc6b025)](https://sonarqube.corp.redhat.com/dashboard?id=ansible_aap-gateway)
[![Security Hotspots](https://sonarqube.corp.redhat.com/api/project_badges/measure?project=ansible_aap-gateway&metric=security_hotspots&token=sqb_19096b3174c8d45029973fd724f27e21efc6b025)](https://sonarqube.corp.redhat.com/dashboard?id=ansible_aap-gateway)
[![Bugs](https://sonarqube.corp.redhat.com/api/project_badges/measure?project=ansible_aap-gateway&metric=bugs&token=sqb_19096b3174c8d45029973fd724f27e21efc6b025)](https://sonarqube.corp.redhat.com/dashboard?id=ansible_aap-gateway)
[![Code Smells](https://sonarqube.corp.redhat.com/api/project_badges/measure?project=ansible_aap-gateway&metric=code_smells&token=sqb_19096b3174c8d45029973fd724f27e21efc6b025)](https://sonarqube.corp.redhat.com/dashboard?id=ansible_aap-gateway)

# AAP Services Gateway

The goal for a platform wide gateway is to provide a single entry point that sits in front of all the services within AAP. Right now there are a couple issues with how authentication is achieved within the platform:

* [JIRA Epic](https://issues.redhat.com/browse/ANSTRAT-37)
* [JIRA Plan View](https://issues.redhat.com/secure/PortfolioReportView.jspa?r=Jivql#plan/backlog)
* [POC Code](https://github.com/ansible/aap-gateway-poc)
* [Google Drive](https://drive.google.com/drive/u/0/folders/18HxXa1K7Joeicnx43RCVVlhWHDnXf-Cx)
* [Miro Arch Diagrams](https://miro.com/app/board/uXjVM3achZw=/)
* [Miro Auth Brainstorming](https://miro.com/app/board/uXjVM2exfpo=/)


Gateway is currently in design phase, more information will be available later.

This repo is internal only at this time. 

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

## Proxy Configuration

Configure your local controller and hub instances in tools/configs/proxy.yaml. This will be used to create the envoy configuration from tools/templates/envoy.yaml.j2.


```
services:
  hub:
    use_tls: false              <- set to true if the instance you're proxying to uses HTTPS
    proxy_root: /api/hub/       <- path on the proxy host that the service will be served from
    service_root: /api/galaxy/  <- path on the service host where the service's API lives

    load_balance:               <- multiple hosts for the service can be listed here for load balancing
      - address: "localhost"    <- hostname where the service is running
        port: 5001              <- port that the service is listening on
```

## Run the Gateway with Automation Hub Example Container

0. Create a python virtual env: `python3 -m venv venv`
1. Build the dev env: `make docker-compose-build`
2. Configure the proxy to talk to the Hub example container:

```yaml
tools/configs/proxy.yaml
[...]
  hub:
    use_tls: true
    proxy_root: /api/hub/
    service_root: /api/galaxy/

    load_balance:
      - address: "localhost"
        port: 5043
```

3. Run the dev environment: `make docker-compose`
4. Once the stack has initialized, create a new super user:

```
docker exec -it tools_aap_gw_1 /opt/aap_gateway/venv/bin/python /opt/aap_gateway/aap_gateway/manage.py createsuperuser
Failed to load file /etc/gateway/SECRET_KEY, will use default
Username: foo
Email address: foo@bar.com
Password:
Password (again):
The password is too similar to the username.
This password is too short. It must contain at least 8 characters.
Bypass password validation and create user anyway? [y/N]: y
Superuser created successfully.
```

5. In a new terminal start the hub example container: `make example/hub`
6. Navigate to https://localhost:9080/api/gateway/v1/login/ and sign in with your new user
7. Once the Hub container has finished initializing navigate to https://localhost:9080/api/hub/_ui/v1/me/

Congrats! You've just logged into Hub with your AAP Gateway Credentials