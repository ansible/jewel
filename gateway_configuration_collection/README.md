# Ansible Collection - ansible.gateway_configuration

## Description

This collection provides Ansible Roles for configuration of the AAP gateway.
Roles manage gateway data through gateway API.

## Available Roles

|       Role name       |          Data variable          |                    README                     |
|:---------------------:|:-------------------------------:|:---------------------------------------------:|
|    authenticators     |    `gateway_authenticators`     |    [link](roles/authenticators/README.md)     |
|  authenticator_maps   |  `gateway_authenticator_maps`   |  [link](roles/authenticator_maps/README.md)   |
|      http_ports       |      `gateway_http_ports`       |      [link](roles/http_ports/README.md)       |
|     organizations     |     `gateway_organizations`     |     [link](roles/organizations/README.md)     |
|   service_clusters    |   `gateway_service_clusters`    |   [link](roles/service_clusters/README.md)    |
|    service_keys    |    `gateway_service_keys`    |    [link](roles/service_keys/README.md)    |
|     service_nodes     |     `gateway_service_nodes`     |     [link](roles/service_nodes/README.md)     |
| role_user_assignments | `gateway_role_user_assignments` | [link](roles/role_user_assignments/README.md) |
|        routes         |        `gateway_routes`         |        [link](roles/routes/README.md)         | 
|       services        |       `gateway_services`        |       [link](roles/services/README.md)        |
|       settings        |       `gateway_settings`        |       [link](roles/settings/README.md)        |
|         teams         |         `gateway_teams`         |         [link](roles/teams/README.md)         |
|         users         |         `gateway_users`         |         [link](roles/users/README.md)         |

### Example: Ansible Playbook

```yaml
- name: Playbook to configure automation platform gateway data
  hosts: localhost
  connection: local
  vars:
    gateway_hostname: https://localhost:8000
    gateway_validate_certs: False
    gateway_username: admin
    gateway_password: password
    gateway_configuration_secure_logging: False
    gateway_state: present  # default value
  roles:
  - { role: ansible.gateway_configuration.settings, when: gateway_settings is defined }
  - { role: ansible.gateway_configuration.users, when: gateway_users is defined }
  - { role: ansible.gateway_configuration.organizations, when: gateway_organizations is defined }
  - { role: ansible.gateway_configuration.teams, when: gateway_teams is defined }
  - { role: ansible.gateway_configuration.authenticators, when: gateway_authenticators is defined }
  - { role: ansible.gateway_configuration.authenticator_maps, when: gateway_authenticator_maps is defined }
  - { role: ansible.gateway_configuration.http_ports, when: gateway_http_ports is defined }
  - { role: ansible.gateway_configuration.service_clusters, when: gateway_service_clusters is defined }
  - { role: ansible.gateway_configuration.service_keys, when: gateway_service_keys is defined }
  - { role: ansible.gateway_configuration.service_nodes, when: gateway_service_nodes is defined }
  - { role: ansible.gateway_configuration.services, when: gateway_services is defined }
  - { role: ansible.gateway_configuration.routes, when: gateway_routes is defined }
  - { role: ansible.gateway_configuration.role_user_assignments, when: gateway_role_user_assignments is defined }
```

## Variables

### Global variables

| Variable Name             | Default Value | Required | Description                                                                                                                                                                                                                                             |  Example  |
|:--------------------------|:-------------:|:--------:|:--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|:---------:|
| `gateway_state`           |   "present"   |    no    | The state all objects will take unless overridden by object default                                                                                                                                                                                     | 'absent'  |
| `gateway_hostname`        |      ""       |   yes    | URL to the automation platform gateway server.                                                                                                                                                                                                          | 127.0.0.1 |
| `gateway_validate_certs`  |    `True`     |    no    | Whether or not to validate the automation platform gateway server's SSL certificate.                                                                                                                                                                    |           |
| `gateway_username`        |      ""       |    no    | user on the automation platform gateway server. Either username / password or oauthtoken need to be specified.                                                                                                                                          |           |
| `gateway_password`        |      ""       |    no    | gateway user's password on the automation platform gateway server. This should be stored in an Ansible Vault at vars/gateway-secrets.yml or elsewhere and called from a parent playbook. Either username / password or oauthtoken need to be specified. |           |
| `gateway_oauthtoken`      |      ""       |    no    | gateway user's token on the automation platform gateway server. This should be stored in an Ansible Vault at or elsewhere and called from a parent playbook. Either username / password or oauthtoken need to be specified.                             |           |
| `gateway_request_timeout` |     `10`      |    no    | Specify the timeout in seconds Ansible should use in requests to the gateway host.                                                                                                                                                                      |           |

### Data variables

Role names are used in role-specific variables (i.e. `gateway_<role_name>` => `gateway_service_clusters`).
They are placed in the `roles` section after `when:` keyword  (see
chapter [Example Playbook](#example-ansible-playbook))

| Variable Name         | Default Value | Required | Description                                 | Example             |
|:----------------------|:-------------:|:--------:|:--------------------------------------------|:--------------------|
| `gateway_<role_name>` |      ---      |   N/A    | Data structure describing your role entries | (see Role's README) |

### State variable

Every data item defines the desired final state (except role `settings`).
There are 4 possible states, which are:

| Name       | Default | Description                                                              |
|:-----------|:-------:|:-------------------------------------------------------------------------|
| `present`  | `True`  | Ensures the item is created or updated                                   |
| `exists`   | `False` | Checks whether the item exists. If not, the playbook fails               |
| `enforced` | `False` | Reserved, not implemented yet                                            |
| `absent`   | `False` | Ensures the item is deleted. If it doesn't exist, no action is performed |

State is configured globally for all objects (see `gateway_state` in the
chapter [Example Playbook](#example-ansible-playbook))
or is overriden by `state` in each item

**Example**

```yaml
gateway_service_clusters:
- name: Automation Controller
  state: exists
- name: AAP gateway
  service_type: gateway
# state: present  # by default
```

### Secure Logging Variables

Enables/Disables logging of the role tasks. When secure logging is `True`, role is not logged,
typically because it contains sensitive information.  
Set this value to `True` if you will be providing your sensitive values from elsewhere.

There is global and role-specific variable:

| Variable Name                                      | Default Value | Required | Description                                                                                |
|:---------------------------------------------------|:-------------:|:--------:|:-------------------------------------------------------------------------------------------|
| `gateway_configuration_secure_logging`             |    `False`    |    no    | This variable is shared across multiple roles. Can be overriden by role-specific variable. |
| `gateway_configuration_<role_name>_secure_logging` |    custom     |    no    | Role-specific. Bigger priority than global one.                                            |

Variables compliment each other.
`gateway_configuration_<role_name>_secure_logging` defaults to the value of `gateway_configuration_secure_logging` if it
is not explicitly called.
This allows for secure logging to be toggled for the entire suite of configuration roles with a single variable, or for
the role to selectively use it.

TODO: move to role's README
The role defaults to False as normally the add service node task does not include sensitive information.
If both variables are not set, secure logging defaults to false.

### Enforcing Defaults

Enabling these variables enforce default values on options that are optional in the gateway API.
This should be enabled to enforce configuration and prevent configuration drift. It is recommended to be enabled,
however it is not enforced by default.

TODO: This is not implemented by API yet.

Enabling this will enforce configuration without specifying every option in the configuration files.

| Variable Name                                        | Default Value | Required | Description                                                                                |
|:-----------------------------------------------------|:-------------:|:--------:|:-------------------------------------------------------------------------------------------|
| `gateway_configuration_enforce_defaults`             |    `False`    |    no    | This variable is shared across multiple roles. Can be overriden by role-specific variable. |
| `gateway_configuration_<role_name>_enforce_defaults` |    custom     |    no    | Role-specific. Bigger priority than global one.                                            |

Variables compliment each other.
`gateway_configuration_<role_name>_enforce_defaults` defaults to the value of `gateway_configuration_enforce_defaults`
if it is not explicitly called.
This allows for enforced defaults to be toggled for the entire suite of gateway configuration roles with a single
variable, or for the role to selectively use it.
If both variables are not set, enforcing default values is not done.

### Asynchronous Retry Variables

The following Variables set asynchronous retries for the role.
If neither of the retries or delays are set, they will default to their respective defaults.
This allows for all items to be created, then checked that the task finishes successfully.
This also speeds up the overall role.

| Variable Name                                     |                Default Value                | Required | Description                                                                                                                                                 |
|:--------------------------------------------------|:-------------------------------------------:|:--------:|:------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `gateway_configuration_async_retries`             |                     30                      |    no    | This variable sets the number of retries to attempt for the role globally.                                                                                  |
| `gateway_configuration_<role_name>_async_retries` | `{{ gateway_configuration_async_retries }}` |    no    | This variable sets the number of retries to attempt for the role.                                                                                           |
| `gateway_configuration_async_delay`               |                      1                      |    no    | This sets the delay between retries for the role globally.                                                                                                  |
| `gateway_configuration_<role_name>_async_delay`   |  `{{ gateway_configuration_async_delay }}`  |    no    | This sets the delay between retries for the role.                                                                                                           |
| `gateway_configuration_async_dir`                 |                   `null`                    |    no    | Sets the directory to write the results file for async tasks. The default value is set to `null` which uses the Ansible Default of `/root/.ansible_async/`. |

## License

[GPLv3](https://github.com/ansible/aap-gateway/gateway_configuration_collection/COPYING)

## Authors

[Sean Sullivan](https://github.com/sean-m-sullivan)
[Martin Slemr](https://github.com/slemrmartin)
