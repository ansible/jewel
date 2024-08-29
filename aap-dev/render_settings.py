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


service_options = ('controller', 'eda')

if sys.argv[-1] in service_options:
    service = sys.argv[-1]
else:
    service = service_options[0]


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

settings_path = os.path.join(os.path.dirname(__file__), f'{service}_settings_template.py')

with open(settings_path, 'r') as f:
    settings_content = f.read()


new_settings = settings_content.replace('# GATEWAY_SERVICE_SECRET', f'GATEWAY_SERVICE_SECRET = r"{key}"')

print(new_settings)
