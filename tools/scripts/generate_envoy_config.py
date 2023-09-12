from sys import exit

import jinja2
import yaml

# In production this will be done by ansible, using the template file provided here.
config = {}
template = ""
with open("/etc/gateway/proxy.yaml", "r") as f:
    config = yaml.safe_load(f)

environment = jinja2.Environment(autoescape=True, loader=jinja2.FileSystemLoader("/templates/"))

template = environment.get_template("envoy.yaml.j2")

with open("/etc/gateway/envoy.yaml", "w") as f:
    try:
        f.write(template.render(**config))
    except Exception as e:
        print("Failed to render template")
        print(e)
        exit(255)
