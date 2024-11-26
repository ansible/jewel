import yaml
from django.core.management.base import BaseCommand, CommandError

from aap_gateway_api.models import AdditionalRoute, HTTPPort, ServiceAPIRoute, ServiceCluster, ServiceNode

SERVICES = ["gateway", "hub", "controller", "eda"]


class Command(BaseCommand):
    help = "Deprecated: Initialize gateway service configuration from a proxy.yml file."

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
            enable_gateway_auth = cfg.get("enable_gateway_auth", True)

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
                    "enable_gateway_auth": enable_gateway_auth,
                },
            )

            ServiceNode.objects.filter(service_cluster=service).delete()

            for instance in cfg["nodes"]:
                ServiceNode.objects.create(name=f"Node {name} - {instance['address']}", service_cluster=service, **instance)

            if not cfg.get('additional_routes'):
                continue

            for additional_route in cfg['additional_routes']:
                # a gateway_path MUST be specified
                gateway_path = additional_route["gateway_path"]
                # default to the gateway_path if service_path not given
                service_path = additional_route.get('service_path', gateway_path)
                # the route can have it's own api port that is different from the service's
                # but we will default to the service api port if not given
                additional_route_api_port = additional_route.get('api_port', cfg["api_port"])
                # the route can specifiy gateway auth, but will default to the setting for the service
                additional_route_enable_gateway_auth = additional_route.get("enable_gateway_auth", enable_gateway_auth)

                self.stdout.write(f'Creating {gateway_path} route for {service_type}')

                AdditionalRoute.objects.update_or_create(
                    http_port=api_port,
                    gateway_path=gateway_path,
                    name=additional_route["name"],
                    defaults={
                        "service_port": additional_route_api_port,
                        "service_path": service_path,
                        "is_service_https": cfg["use_tls"],
                        "description": additional_route.get("description", ""),
                        "service_cluster": service,
                        "enable_gateway_auth": additional_route_enable_gateway_auth,
                    },
                )
