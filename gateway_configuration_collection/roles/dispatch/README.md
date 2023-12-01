# gateway_configuration.dispatch

## Description

An Ansible Role to run all roles in the infra.gateway_configuration collection.

## Variables

Each role has its own variables, for information on those please see each role which this role will call. This role has one key variable `gateway_configuration_dispatcher_roles` and its default value is shown below:

```yaml
gateway_configuration_dispatcher_roles:
  - {role: settings, var: gateway_settings, tags: settings}
  - {role: users, var: gateway_user_accounts, tags: users}
```

Note that each item has three elements:

- `role` which is the name of the role within infra.gateway_configuration
- `var` which is the variable which is used in that role. We use this to prevent the role being called if the variable is not set
- `tags` the tags which are applied to the role so it is possible to apply tags to a playbook using the dispatcher with these tags.

It is possible to redefine this variable with a subset of roles or with different tags. In general we suggest keeping the same structure and perhaps just using a subset.

### Authentication

|Variable Name|Default Value|Required|Description|Example|
|:---|:---:|:---:|:---|:---|
|`gateway_state`|"present"|no|The state all objects will take unless overridden by object default|'absent'|
|`gateway_hostname`|""|yes|URL to the automation platform gateway server.|127.0.0.1|
|`gateway_validate_certs`|`True`|no|Whether or not to validate the automation platform gateway server's SSL certificate.||
|`gateway_username`|""|no|user on the automation platform gateway server. Either username / password or oauthtoken need to be specified.||
|`gateway_password`|""|no|gateway user's password on the automation platform gateway server. This should be stored in an Ansible Vault at vars/gateway-secrets.yml or elsewhere and called from a parent playbook. Either username / password or oauthtoken need to be specified.||
|`gateway_oauthtoken`|""|no|gateway user's token on the automation platform gateway server. This should be stored in an Ansible Vault at or elsewhere and called from a parent playbook. Either username / password or oauthtoken need to be specified.||
|`gateway_request_timeout`|`10`|no|Specify the timeout in seconds Ansible should use in requests to the gateway host.||

### Secure Logging Variables

The role defaults to False as normally most projects task does not include sensitive information.
Each role the dispatch role calls has a separate variable which can be turned on to enforce secure logging for that role but defaults to the value of gateway_configuration_secure_logging if it is not explicitly called. This allows for secure logging to be toggled for the entire suite of configuration roles with a single variable, or for the user to selectively use it. If neither value is set then each role has a default value of true or false depending on the Red Hat COP suggestions.

|Variable Name|Default Value|Required|Description|
|:---:|:---:|:---:|:---:|
|`gateway_configuration_secure_logging`|""|no|This variable enables secure logging as well, but is shared across multiple roles, see above.|

### Asynchronous Retry Variables

The following Variables set asynchronous retries for the role.
If neither of the retries or delay or retries are set, they will default to their respective defaults.
This allows for all items to be created, then checked that the task finishes successfully.
This also speeds up the overall role. Each individual role has its own variable which can allow the individual setting of values. See each role for more the variable names.

|Variable Name|Default Value|Required|Description|
|:---:|:---:|:---:|:---:|
|`gateway_configuration_async_retries`|30|no|This variable sets the number of retries to attempt for the role globally.|
|`gateway_configuration_async_delay`|1|no|This sets the delay between retries for the role globally.|

## Playbook Examples

### Standard Role Usage

```yaml
---
- name: Playbook to configure automation platform gateway post installation
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
    - infra.gateway_configuration.dispatch
```

## License

[Apache-2.0](https://github.com/ansible/aap-gateway/blob/devel/LICENSE.md)

## Author
[Sean Sullivan](https://github.com/sean-m-sullivan)
