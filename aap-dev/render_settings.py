# This runs a docker command against the gateway container to get
# what will become the GATEWAY_SERVICE_SECRET in settings for AWX or EDA
# this is service-specific, so first CLI argument is the service identifier
import subprocess
import sys
import os
import re


def escape_ansi(line):
    ansi_escape = re.compile(r'(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]')
    return ansi_escape.sub('', line)


service_options = ('controller', 'eda', 'galaxy', 'lightspeed')
service = sys.argv[-1]

if service not in service_options:
    raise RuntimeError(f'Got service arg {service} which is not one of {service_options}')


COMMAND = f'docker exec -it aap_gw_1 aap-gateway-manage generate_service_secret {service}'

result = subprocess.run(COMMAND.split(), stdout=subprocess.PIPE)

key = str(result.stdout, encoding='utf-8').strip()

# We might get a warning like
# Failed to load file /etc/ansible-automation-platform/gateway/SECRET_KEY, will use default
# so just sanitize this as much as possible
if '_' in key:
    for sub_part in reversed(key.split()):
        if '[0m' in sub_part:
            continue  # strip ansii encodings
        key = sub_part
        break

# Newline and ansi may still remain
key = escape_ansi(key).strip()

service_settings_path = os.path.join(os.path.dirname(__file__), f'settings_template_{service}.py')

service_settings_content = ''
if os.path.exists(service_settings_path):
    with open(service_settings_path, 'r') as f:
        service_settings_content = f.read()


common_settings_path = os.path.join(os.path.dirname(__file__), 'settings_template_common.py')


with open(common_settings_path, 'r') as f:
    common_settings_content = f.read()


settings_content = '\n'.join([service_settings_content, common_settings_content])


new_settings = settings_content.replace('# GATEWAY_SERVICE_SECRET', f'GATEWAY_SERVICE_SECRET = r"{key}"')

print(new_settings)
