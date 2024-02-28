import yaml
from django.core.management.base import BaseCommand, CommandError

from aap_gateway_api.models.service import AdditionalRoute, HTTPPort, ServiceAPIRoute, ServiceCluster, ServiceNode

SERVICES = ["gateway", "hub", "controller", "eda"]


class Command(BaseCommand):
    help = "Deprecated: Initialize Gateway service configuration from a proxy.yml file."

    def add_arguments(self, parser):
        parser.add_argument("--config", type=str, help="Service configuration yml file.", required=True)

    def handle(self, *args, **options):
        config = {}

        try:
            with open(options["config"], "r") as f:
                config = yaml.safe_load(f)
        except FileNotFoundError:
            raise CommandError(f"{options['config']} does not exist.")

        if type(config) is not dict:
            raise CommandError(f"{options['config']} is not valid YAML.")

        self.stdout.write(f'Creating listener on port {config["proxy"]["api_port"]}')
        api_port, _ = HTTPPort.objects.update_or_create(
            name=f"port-{config['proxy']['api_port']}",
            is_api_port=True,
            defaults={"number": config["proxy"]["api_port"], "use_https": config["proxy"]["use_tls"]},
        )

        services = config.get("services", {})
        for name in services:
            cfg = services[name]
            service_type = cfg["type"]

            if service_type not in SERVICES:
                raise CommandError(f"{service_type} is not allowed.")

            self.stdout.write(f'Creating cluster for {service_type}')
            service, _ = ServiceCluster.objects.get_or_create(name=service_type, service_type=service_type)

            api_route, _ = ServiceAPIRoute.objects.update_or_create(
                service_cluster=service,
                defaults={
                    "name": f"{name} api",
                    "service_port": cfg["api_port"],
                    "service_path": cfg["service_root"],
                    "is_service_https": cfg["use_tls"],
                    "api_slug": name,
                    "order": cfg.get("order", 50),
                },
            )

            ServiceNode.objects.filter(service_cluster=service).delete()

            for instance in cfg["nodes"]:
                ServiceNode.objects.create(name=f"Node {name} - {instance['address']}", service_cluster=service, **instance)

            if service_type == "hub":
                self.stdout.write(f'Creating /v2/ route for {service_type}')
                AdditionalRoute.objects.update_or_create(
                    http_port=api_port,
                    gateway_path="/v2/",
                    name=f"{name}-container-registry",
                    defaults={
                        "service_port": cfg["api_port"],
                        "service_path": "/v2/",
                        "is_service_https": cfg["use_tls"],
                        "description": "Hub Container Registry.",
                        "service_cluster": service,
                        "enable_gateway_auth": True,
                    },
                )
