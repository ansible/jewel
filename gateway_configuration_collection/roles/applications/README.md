# ansible.gateway_configuration.applications

## Description

An Ansible Role to create/update/remove Applications on Ansible gateway.

## Variables

|Variable Name|Default Value|Required|Description|Example|
|:---|:---:|:---:|:---|:---|
|`gateway_state`|"present"|no|The state all objects will take unless overridden by object default|'absent'|
|`gateway_hostname`|""|yes|URL to the Ansible gateway Server.|127.0.0.1|
|`gateway_validate_certs`|`True`|no|Whether or not to validate the Ansible gateway Server's SSL certificate.||
|`gateway_username`|""|no|Admin User on the Ansible gateway Server. Either username / password or oauthtoken need to be specified.||
|`gateway_password`|""|no|Gateway Admin User's password on the Ansible gateway Server. This should be stored in an Ansible Vault at vars/gateway-secrets.yml or elsewhere and called from a parent playbook. Either username / password or oauthtoken need to be specified.||
|`gateway_oauthtoken`|""|no|Gateway Admin User's token on the Ansible gateway Server. This should be stored in an Ansible Vault at or elsewhere and called from a parent playbook. Either username / password or oauthtoken need to be specified.||
|`gateway_request_timeout`|`10`|no|Specify the timeout in seconds Ansible should use in requests to the gateway host.||
|`gateway_applications`|`see below`|yes|Data structure describing your applications, described below. Alias: applications ||

### Enforcing defaults

The following Variables compliment each other.
If Both variables are not set, enforcing default values is not done.
Enabling these variables enforce default values on options that are optional in the gateway API.
This should be enabled to enforce configuration and prevent configuration drift. It is recommended to be enabled, however it is not enforced by default.

Enabling this will enforce configuration without specifying every option in the configuration files.

'gateway_configuration_applications_enforce_defaults' defaults to the value of 'gateway_configuration_enforce_defaults' if it is not explicitly called. This allows for enforced defaults to be toggled for the entire suite of gateway configuration roles with a single variable, or for the user to selectively use it.

|Variable Name|Default Value|Required|Description|
|:---:|:---:|:---:|:---:|
|`gateway_configuration_applications_enforce_defaults`|`False`|no|Whether or not to enforce default option values on only the applications role|
|`gateway_configuration_enforce_defaults`|`False`|no|This variable enables enforced default values as well, but is shared across multiple roles, see above.|

### Secure Logging Variables

The following Variables compliment each other.
If Both variables are not set, secure logging defaults to false.
The role defaults to False as normally the add application task does not include sensitive information.
gateway_configuration_applications_secure_logging defaults to the value of gateway_configuration_secure_logging if it is not explicitly called. This allows for secure logging to be toggled for the entire suite of gateway configuration roles with a single variable, or for the user to selectively use it.

|Variable Name|Default Value|Required|Description|
|:---:|:---:|:---:|:---:|
|`gateway_configuration_applications_secure_logging`|`False`|no|Whether or not to include the sensitive Application role tasks in the log. Set this value to `True` if you will be providing your sensitive values from elsewhere.|
|`gateway_configuration_secure_logging`|`False`|no|This variable enables secure logging as well, but is shared across multiple roles, see above.|

### Asynchronous Retry Variables

The following Variables set asynchronous retries for the role.
If neither of the retries or delay or retries are set, they will default to their respective defaults.
This allows for all items to be created, then checked that the task finishes successfully.
This also speeds up the overall role.

|Variable Name|Default Value|Required|Description|
|:---:|:---:|:---:|:---:|
|`gateway_configuration_async_retries`|30|no|This variable sets the number of retries to attempt for the role globally.|
|`gateway_configuration_applications_async_retries`|`{{ gateway_configuration_async_retries }}`|no|This variable sets the number of retries to attempt for the role.|
|`gateway_configuration_async_delay`|1|no|This sets the delay between retries for the role globally.|
|`gateway_configuration_applications_async_delay`|`gateway_configuration_async_delay`|no|This sets the delay between retries for the role.|
|`gateway_configuration_async_dir`|`null`|no|Sets the directory to write the results file for async tasks. The default value is set to `null` which uses the Ansible Default of `/root/.ansible_async/`.|

## Data Structure

### Application Variables

|Variable Name|Default Value|Required|Type|Description|
|:---:|:---:|:---:|:---:|:---:|
|`name`|""|yes|str|Name of application|
|`new_name`|""|no|str|Setting this option will change the existing name (looked up via the name field).|
|`algorithm`|""|no|str|The OIDC token signing algorithm for this application, "", "RS256", "HS256".|
|`organization`|""|yes|str|Name of the organization for the application|
|`description`|""|no|str|Description to use for the application.|
|`authorization_grant_type`|"password"|yes|str|Grant type for tokens in this application, "password" or "authorization-code"|
|`client_type`|"public"|yes|str|Application client type, "confidential" or "public"|
|`redirect_uris`|""|no|str|Allowed urls list, space separated. Required with "authorization-code" grant type|
|`skip_authorization`|"false"|yes|bool|Set True to skip authorization step for completely trusted applications.|
|`state`|`present`|no|str|Desired state of the application.|
|`post_logout_redirect_uris`|""|no|str|Allowed Post Logout URIs list, space separated.|
|`user`|""|no|str|The user who owns this application.|

### Standard Application Data Structure

#### Json Example

```json
 {
    "gateway_applications": [
      {
        "name": "gateway Config Default Application",
        "description": "Generic application, which can be used for oauth tokens",
        "organization": "Default",
        "state": "present",
        "client_type": "confidential",
        "authorization_grant_type": "password"
      }
    ]
}
```

#### Yaml Example

```yaml
---
gateway_applications:
  - name: "gateway Config Default Application"
    description: "Generic application, which can be used for oauth tokens"
    organization: "Default"
    state: "present"
    client_type: "confidential"
    authorization_grant_type: "password"
```

## Playbook Examples

### Standard Role Usage

```yaml
- name: Playbook to configure ansible gateway post installation
  hosts: localhost
  connection: local
  # Define following vars here, or in gateway_configs/gateway_auth.yml
  # gateway_hostname: ansible-gateway-web-svc-test-project.example.com
  # gateway_username: admin
  # gateway_password: changeme
  pre_tasks:
    - name: Include vars from gateway_configs directory
      ansible.builtin.include_vars:
        dir: ./yaml
        ignore_files: [gateway_config.yml.template]
        extensions: ["yml"]
  roles:
    - {role: infra.gateway_configuration.applications, when: gateway_applications is defined}
```

## License

[Apache-2.0](https://github.com/ansible/aap-gateway/blob/devel/LICENSE.md)
