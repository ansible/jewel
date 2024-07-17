# This runs a docker command against the gateway container to get
# what will become the GATEWAY_SERVICE_SECRET in settings for AWX or EDA
# this is service-specific, so first CLI argument is the service identifier
import subprocess
import sys

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

print(key)
