FROM envoyproxy/envoy:v1.24-latest

RUN apt update && apt install -y python3-pip --no-install-recommends && pip install jinja2 PyYAML

COPY tools/scripts/generate_envoy_config.py /scripts/
COPY tools/scripts/envoy-entrypoint.sh /scripts/
COPY tools/templates/envoy.yaml.j2 /templates/

RUN chmod u+x /scripts/envoy-entrypoint.sh

ENTRYPOINT /scripts/envoy-entrypoint.sh