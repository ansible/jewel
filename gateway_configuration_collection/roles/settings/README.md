# gateway_configuration.settings

An Ansible role to alter Settings on Ansible Automation gateway settings.

## Variables

|Variable Name|Default Value|Required|Description|Example|
|:---|:---:|:---:|:---|:---|
|`gateway_state`|"present"|no|The state all objects will take unless overridden by object default|'absent'|
|`gateway_hostname`|""|yes|URL to the automation platform gateway server.|127.0.0.1|
|`gateway_validate_certs`|`True`|no|Whether or not to validate the automation platform gateway server's SSL certificate.||
|`gateway_username`|""|no|user on the automation platform gateway server. Either username / password or oauthtoken need to be specified.||
|`gateway_password`|""|no|gateway user's password on the automation platform gateway server. This should be stored in an Ansible Vault at vars/gateway-secrets.yml or elsewhere and called from a parent playbook. Either username / password or oauthtoken need to be specified.||
|`gateway_oauthtoken`|""|no|gateway user's token on the automation platform gateway server. This should be stored in an Ansible Vault at or elsewhere and called from a parent playbook. Either username / password or oauthtoken need to be specified.||
|`gateway_request_timeout`|`10`|no|Specify the timeout in seconds Ansible should use in requests to the gateway host.||
|`gateway_settings`|`see below`|yes|Data structure describing your settings described below.||

### Secure Logging Variables

The following Variables compliment each other.
If Both variables are not set, secure logging defaults to false.
The role defaults to False as normally the add settings task does not include sensitive information.
gateway_configuration_settings_secure_logging defaults to the value of gateway_configuration_secure_logging if it is not explicitly called. This allows for secure logging to be toggled for the entire suite of configuration roles with a single variable, or for the user to selectively use it.

|Variable Name|Default Value|Required|Description|
|:---:|:---:|:---:|:---:|
|`gateway_configuration_settings_secure_logging`|`False`|no|Whether or not to include the sensitive Settings role tasks in the log. Set this value to `True` if you will be providing your sensitive values from elsewhere.|
|`gateway_configuration_secure_logging`|`False`|no|This variable enables secure logging as well, but is shared across multiple roles, see above.|

### Asynchronous Retry Variables

The following Variables set asynchronous retries for the role.
If neither of the retries or delay or retries are set, they will default to their respective defaults.
This allows for all items to be created, then checked that the task finishes successfully.
This also speeds up the overall role.

|Variable Name|Default Value|Required|Description|
|:---:|:---:|:---:|:---:|
|`gateway_configuration_async_retries`|30|no|This variable sets the number of retries to attempt for the role globally.|
|`gateway_configuration_settings_async_retries`|`{{ gateway_configuration_async_retries }}`|no|This variable sets the number of retries to attempt for the role.|
|`gateway_configuration_async_delay`|1|no|This sets the delay between retries for the role globally.|
|`gateway_configuration_settings_async_delay`|`gateway_configuration_async_delay`|no|This sets the delay between retries for the role.|
|`gateway_configuration_async_dir`|`null`|no|Sets the directory to write the results file for async tasks. The default value is set to `null` which uses the Ansible Default of `/root/.ansible_async/`.|

## Data Structure

Provide settings as a single dict under `settings`.

### Setting Variables

|Variable Name|Default Value|Required|Description|
|:---:|:---:|:---:|:---:|
|`settings`|{}|yes|Dict of key-value pairs of settings|

### Standard Setting Data Structure - as a dict

#### Json Dict Example

```json
{
  "gateway_settings": {
    "gateway_token_name": "X-AAP-GW-TOKEN",
    "gateway_access_token_expiration": 600,
    "gateway_basic_auth_enabled": true,
    "gateway_proxy_url": "https://localhost:9080",
    "gateway_proxy_url_ignore_cert": false,
    "password_min_length": 0,
    "password_min_digits": 0,
    "password_min_upper": 0,
    "password_min_special": 0,
    "allow_admins_to_set_insecure": false
  }
}

```

#### Yaml Dict Example

```yaml
---
gateway_settings:
  gateway_token_name: X-AAP-GW-TOKEN
  gateway_access_token_expiration: 600
  gateway_basic_auth_enabled: true
  gateway_proxy_url: https://localhost:9080
  gateway_proxy_url_ignore_cert: false
  password_min_length: 0
  password_min_digits: 0
  password_min_upper: 0
  password_min_special: 0
  allow_admins_to_set_insecure: false


```

## Playbook Examples

### Standard Role Usage

```yaml
---
- name: Playbook to configure automation platform gateway settings
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
    - {role: infra.gateway_configuration.settings, when: gateway_settings is defined}
```

## License

[Apache-2.0](https://github.com/ansible/aap-gateway/blob/devel/LICENSE.md)

## Author
[Sean Sullivan](https://github.com/sean-m-sullivan)
