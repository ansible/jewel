[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=ansible_aap-gateway&metric=alert_status&token=f0397faea52184c1476deaeb829e9af65c61693c)](https://sonarcloud.io/summary/new_code?id=ansible_aap-gateway)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=ansible_aap-gateway&metric=coverage&token=f0397faea52184c1476deaeb829e9af65c61693c)](https://sonarcloud.io/summary/new_code?id=ansible_aap-gateway)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=ansible_aap-gateway&metric=vulnerabilities&token=f0397faea52184c1476deaeb829e9af65c61693c)](https://sonarcloud.io/summary/new_code?id=ansible_aap-gateway)
[![Security Rating](https://sonarcloud.io/api/project_badges/measure?project=ansible_aap-gateway&metric=security_rating&token=f0397faea52184c1476deaeb829e9af65c61693c)](https://sonarcloud.io/summary/new_code?id=ansible_aap-gateway)
[![Bugs](https://sonarcloud.io/api/project_badges/measure?project=ansible_aap-gateway&metric=bugs&token=f0397faea52184c1476deaeb829e9af65c61693c)](https://sonarcloud.io/summary/new_code?id=ansible_aap-gateway)
[![Code Smells](https://sonarcloud.io/api/project_badges/measure?project=ansible_aap-gateway&metric=code_smells&token=f0397faea52184c1476deaeb829e9af65c61693c)](https://sonarcloud.io/summary/new_code?id=ansible_aap-gateway)
[![Maintainability Rating](https://sonarcloud.io/api/project_badges/measure?project=ansible_aap-gateway&metric=sqale_rating&token=f0397faea52184c1476deaeb829e9af65c61693c)](https://sonarcloud.io/summary/new_code?id=ansible_aap-gateway)

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

Configure your local controller and hub instances in tools/configs/proxy.yml. This will be used to create the envoy configuration from tools/templates/envoy.yml.j2.


```
services:
  hub:
    use_tls: false              <- set to true if the instance you're proxying to uses HTTPS
    service_root: /api/galaxy/  <- path on the service host where the service's API lives

    load_balance:               <- multiple hosts for the service can be listed here for load balancing
      - address: "localhost"    <- hostname where the service is running
        port: 5001              <- port that the service is listening on
```

## Starting Gateway

Please have the following prerequisites already installed on your development machine:
  * docker
  * make
  * openssl

1. Create a python virtual environment: `python3 -m venv <location>`
2. Activate the virtual environment: `source <location>/bin/activate`
3. Install the tools for development: `pip install -r requirements/requirements_dev.txt`
4. Optionally generate and edit the proxy config file to point it to services you have running:
    `make tools/generated/proxy.yml`
    ```yml
    [...]
      hub:
        use_tls: true
        service_root: /api/galaxy/
        api_port: 5043
        type: hub

        nodes:
          - address: "localhost"
    [...]
    ```
5. Log into quay.io: `docker login quay.io`
6. Optionally clone `django-ansible-base` if you are going to be making changes to it. If you clone it, it must live directly inside your `aap-gateway` directory, and be called `django-ansible-base`. If you skip this step, the latest git version of `django-ansible-base` will be built into your development image.
7. Start up your environment: `make docker-compose`

This will build an `admin` user with random password (see value for `gateway_admin_password` in `container-startup.yml`) and create any services you have defined in your `proxy.yml` file.

Note: You can force your own password by setting the `ADMIN_PASSWORD` environment variable before running `make docker-compose`.

## Starting other AAP services

See [development doc](docs/development.md)

## Side cars

There are additional services available to be started alongside gateway to enable development. We call these side car containers. When you run an initial `make docker-compose` a file called `container-startup.yml` will be created at the root of your project. If you haven't run `make docker-compose` yet and want to generate the file you can run `make container-startup.yml".

At the beginning of you file you will see the following options:
```
gateway_host: https://localhost:8000
gateway_admin_username: admin
gateway_admin_password: admin
container_reference: 10.0.0.71
```

gateway_host, username and password tell us how to connect to your Gateway instance once its running. This is used to configure things like settings inside your Gateway instance to connect to to the side containers. If you change the admin password, please update it in this file.

`container_reference` is used for several of the authentication mechanisms. For example, SAML works by sending redirects between Gateway and Keycloak through the browser. Because of this we have to tell both Gateway and Keycloak how they will construct the redirect URLs. On the Keycloak side, this is done within the realm configuration and on the Gateway side its done through the SAML settings. The container_reference variable needs to be how your browser will be able to talk to the running containers. Here are some examples of how to choose a proper container_reference.
* If you develop on a mac which runs a Fedora VM which has Gateway running within that and the browser you use to access Gateway runs on the mac. The the VM with the container has its own IP that is mapped to a name like `gateway.home.net`. In this scenario your "container_reference" could be either the IP of the VM or the gateway.home.net friendly name.
* If you are on a Fedora work station running Gateway and also using a browser on your workstation you could use localhost, your work stations IP or hostname as the container_reference.

By default, all side cars are disabled. The next section of the file has lines which say which side containers to start. i.e.:
```
# ldap_enabled: True
```

These can be any valid true or false statements ansible can handle. A `true` value indicates that the container should be started and a `false` leaves the container disabled.

There are two times these variables are checked. First when we run `make docker-compose` an additional step to initialize any containers will be run. These steps vary per container type but all are idempotent so running them multiple times should not cause issues.

Secondly, we have a plumb playbook which will configure your Gateway instance to use the containers. When running the plumb playbook this will only plumb for containers which are initialized.

In addition to this file, there is a file `tools/ansible/vars/container_config.yml` which has default information for the various services. These allow for further customization of the containers (such as default account credentials for services or exposed ports and image versions, etc).

In the following sections of this document we will discuss individual integrations and some of the extended variables which can be set in your container-startup.yml to override the defaults in `tools/ansible/vars/container_config.yml`

### SAML and OIDC Integration
Keycloak can be used as both a SAML and OIDC provider and can be used to test Gateway social auth. This section describes how to build a reference Keycloak instance and plumb it with Gateway for testing purposes.

_Note_: If you are using M1 Mac, refer to building [keycloak image for M1](./docs/keycloak_on_m1.md) documentation.

Once the containers come up a new port (8443 by default) should be exposed and the Keycloak interface should be running on that port. Connect to this through a url like `https://localhost:8443` to confirm that Keycloak has stared. If you wanted to login and look at Keycloak itself you could select the "Administration console" link and log into the UI the username/password set in the container_config.yml file. For more information about Keycloak and links to their documentation see their project at https://github.com/keycloak/keycloak.

#### Additional Configuration
```
keycloak_exposed_port: 8443                         <- The exposed port on the machine running docker
keycloak_username: admin                            <- Admin username and password
keycloak_password: admin
cert_subject: "/C=US/ST=NC/L=Durham/O=gateway/CN="  <- The CN for the self signed cert
oidc_reference:                                     <- See note below
```

Note: SAML works by sending redirects between Gateway and Keycloak through the browser. Because of this we have to tell both Gateway and Keycloak how they will construct the redirect URLs. On the Keycloak side, this is done within the realm configuration and on the Gateway side its done through the SAML settings. The `container_reference` variable in the general section above is used for the configuration.

In addition, OIDC works similar but slightly differently. OIDC has browser redirection but OIDC will also communicate from the Gateway docker instance to the Keycloak docker instance directly. Any hostnames you might have are likely not propagated down into the Gateway container. So we need a method for both the browser and Gateway container to talk to Keycloak. For this we will likely use your machines IP address. This can be passed in as a variable called `oidc_reference`. If unset this will default to container_reference which may be viable for some configurations.


#### Plumbing
The plumbing of Keycloak will:
* Backup and configure a SMAL SP and OIDC authenticator in Gateway. NOTE: the private key of any existing SAML or OIDC authenticators can not be backed up through the API, you need a DB backup to recover this.

Once the playbook is done running both SAML and OIDC should now be setup in your development environment. This realm has three users with the following username/passwords:
1. gateway_unpriv:unpriv123
2. gateway_admin:admin123
3. gateway_auditor:audit123

The first account is a normal user. The second account has the SMAL attribute is_superuser set in Keycloak so will be a super user in Gateway if logged in through SAML. The third account has the SAML is_system_auditor attribute in Keycloak so it will be a system auditor in Gateway if logged in through SAML. To log in with one of these Keycloak users go to the Gateway login screen and <TBD>.

<TBD>
# Note: The OIDC adapter performs authentication only, not authorization. So any user created in Gateway will not have any permissions on it at all.

If you Keycloak configuration is not working and you need to rerun the playbook to try a different `container_reference` or `oidc_reference` you can log into the Keycloak admin console on port 8443 and select the Gateway realm in the upper left drop down. Then make sure you are on "Realm Settings" in the Configure menu option and click the trashcan next to Gateway in the main page window pane. This will completely remove the Gateway ream (which has both SAML and OIDC settings) enabling you to re-run the plumb playbook.

### OpenLDAP Integration

OpenLDAP is an LDAP provider that can be used to test Gateway with LDAP integration.

Once the containers come up two new ports (389, 636 by default) should be exposed and the LDAP server should be running on those ports. The first port (389) is non-SSL and the second port (636) is SSL enabled.

#### Additional Configuration
```
ldap_exposed_ldap_port: 389             <- The ldap port to expose on the machine running docker
ldap_exposed_ldaps_port: 636            <- The ldaps port to expose on the machine running docker
ldap_image_version: 2                   <- The version of the OpenLDAP container to run
ldap_admin_username: admin              <- Username and password
ldap_admin_password: admin
ldap_public_key_file_name: 'ldap.cert'  <- Name of the public cert file in tools/generated/ldap
ldap_private_key_file_name: 'ldap.key'  <- Name of the private key file in tools/generated/ldap
```

Note: LDAP will be communicated to from within the Gateway container. Because of this, we have to tell Gateway how to route traffic to the LDAP container through the `Server URI` authenticator configuration. This setting is constructed via the `container_reference` variable in the general section above.

#### Plumbing
The plumb playbook for OpenLDAP will:

* Backup and configure an LDAP authenticator in Gateway. NOTE: this will back up your existing settings but the password fields can not be backed up through the API, you need a DB backup to recover this.

Note: The default configuration will utilize the non-tls connection. If you want to use the tls configuration you will need to work through TLS negotiation issues because the LDAP server is using a self signed certificate.

Once the playbook is done running LDAP should now be setup in your development environment. This realm has four users with the following username/passwords:
1. ldap_unpriv:unpriv123
2. ldap_admin:admin123
3. ldap_auditor:audit123
4. ldap_org_admin:orgadmin123

The first account is a normal user. The second account will be a super user in Gateway. The third account will be a system auditor in Gateway. The fourth account is an org admin. All users belong to an org called "LDAP Organization". To log in with one of these users go to the Gateway login screen enter the username/password.


### tacacs+ Integration

tacacs+ is an networking protocol that provides external authentication which can be used with Gateway. This section describes how to build a reference tacacs+ instance and plumb it with your Gateway for testing purposes.

Once the containers come up a new port (49) should be exposed and the tacacs+ server should be running on that port.

#### Additional Configuration
```
tacacs_container_version: latest <- Container version
```

#### Plumbing

The plumb playbook will:
* Backup and configure a tacacsplus authenticator in Gateway. NOTE: this will back up your existing settings but the password fields can not be backed up through the API, you need a DB backup to recover this.

Once the playbook is done running tacacs+ should now be setup in your development environment. This server has the accounts listed on https://hub.docker.com/r/dchidell/docker-tacacs
