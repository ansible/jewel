import yaml
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from aap_gateway_api.models import ServiceAPIRoute, ServiceCluster, ServiceNode, ServiceType
from aap_gateway_api.utils.service_id_sync import populate_missing_service_ids

_REQUIRED_SERVICE_FIELDS = ("type", "api_slug", "service_port", "service_path")


class Command(BaseCommand):
    """Sync service IDs for registered clusters and optionally register new services.

    Without --register: populates service_id on every cluster where it is null.
    With --register <config.yml>: upserts service definitions from a YAML config file,
    then populates service_id for any cluster (including newly created ones) that lacks one.
    With --force: re-fetches and overwrites service_id even for clusters that already have one.

    Safe to run on every upgrade. Invoke via::

        aap-gateway-manage sync_service_ids
        aap-gateway-manage sync_service_ids --register /path/to/services.yml
        aap-gateway-manage sync_service_ids --force

    Example YAML for --register::

        services:
          metrics:
            type: metrics
            api_slug: metrics
            service_port: 8443
            service_path: /v1/service-index/
            is_service_https: true
            nodes:
              - address: 10.0.0.5
    """

    help = "Populate service_id for registered clusters; optionally register new services first."

    def add_arguments(self, parser):
        parser.add_argument(
            "--register",
            type=str,
            default=None,
            metavar="CONFIG",
            help="Path to a YAML file defining services to create/update before syncing IDs.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help=(
                "Re-fetch and overwrite service_id for ALL non-gateway clusters, including "
                "those that already have one. Use after a service re-deployment or disaster "
                "recovery to ensure stored IDs match what each service reports."
            ),
        )

    def handle(self, *args, **options):
        """Optionally registers services from config, then populates all missing service_ids.

        With --force, re-fetches service_id for every non-gateway cluster regardless of
        whether one is already stored.

        Args:
            *args: Unused positional arguments.
            **options: Parsed command options (register, force).
        """
        if options["register"]:
            self._register_from_config(options["register"])

        populated, failed = populate_missing_service_ids(force=options["force"])

        if not populated and not failed:
            self.stdout.write("No clusters with missing service_id found.")
            return

        if populated:
            self.stdout.write(self.style.SUCCESS(f"Populated: {', '.join(populated)}"))
        if failed:
            self.stderr.write(self.style.WARNING(f"Failed: {', '.join(failed)}"))

    def _validate_config(self, config, config_path):
        """Validates the parsed YAML config document before any ORM writes.

        Args:
            config: The parsed YAML object.
            config_path: Filesystem path, used only in error messages.

        Raises:
            CommandError: If the document structure or any service entry is invalid.
        """
        if not isinstance(config, dict) or "services" not in config:
            raise CommandError(f"{config_path} must be a YAML mapping with a 'services' key.")

        if not isinstance(config["services"], dict):
            raise CommandError(f"{config_path}: 'services' must be a mapping of name → config.")

        for name, cfg in config["services"].items():
            if not isinstance(cfg, dict):
                raise CommandError(f"{config_path}: entry '{name}' must be a mapping.")

            missing = [f for f in _REQUIRED_SERVICE_FIELDS if f not in cfg]
            if missing:
                raise CommandError(f"{config_path}: entry '{name}' is missing required fields: {', '.join(missing)}.")

            try:
                int(cfg["service_port"])
            except (TypeError, ValueError):
                raise CommandError(f"{config_path}: entry '{name}' service_port must be an integer.")

            self._validate_nodes(name, cfg.get("nodes", []), config_path)

    def _validate_nodes(self, name, nodes, config_path):
        """Validates node entries in a service config.

        Args:
            name: Service name, used in error messages.
            nodes: List of node dicts from the YAML config.
            config_path: Filesystem path, used in error messages.

        Raises:
            CommandError: If any node entry lacks an 'address' key.
        """
        for i, node in enumerate(nodes):
            if not isinstance(node, dict) or "address" not in node:
                raise CommandError(f"{config_path}: entry '{name}' node[{i}] must have an 'address' key.")

    def _register_from_config(self, config_path):
        """Reads a YAML config, validates it, then upserts service records atomically.

        Args:
            config_path: Filesystem path to the YAML config file.

        Raises:
            CommandError: If the file is missing, invalid YAML, fails schema validation,
                or references an unknown ServiceType.
        """
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
        except FileNotFoundError:
            raise CommandError(f"{config_path} does not exist.")
        except yaml.YAMLError as exc:
            raise CommandError(f"{config_path} is not valid YAML: {exc}")

        self._validate_config(config, config_path)
        resolved = self._resolve_service_types(config)
        self._apply_services(resolved)

    def _resolve_service_types(self, config):
        """Maps each service name to its (cfg, ServiceType) pair, raising early on unknown types.

        Args:
            config: Validated YAML dict with a 'services' key.

        Returns:
            Dict of {name: (cfg_dict, ServiceType)}.

        Raises:
            CommandError: If any service references an unknown ServiceType name.
        """
        resolved = {}
        allowed = list(ServiceType.objects.values_list("name", flat=True))
        for name, cfg in config["services"].items():
            service_type = ServiceType.objects.filter(name=cfg["type"]).first()
            if service_type is None:
                raise CommandError(f"Unknown service type '{cfg['type']}' for '{name}'. Allowed: {allowed}")
            resolved[name] = (cfg, service_type)
        return resolved

    def _apply_services(self, resolved):
        """Upserts all resolved services atomically: cluster, nodes, and API route.

        Validates the entire document before touching the database. Wraps all ORM
        writes in a single transaction so either every service is applied or none are.
        Looks up existing clusters by name alone and updates service_type if it changed.
        Nodes are diffed: removed addresses deleted, new addresses created, unchanged kept.

        Args:
            resolved: Dict of {name: (cfg_dict, ServiceType)} from _resolve_service_types.
        """
        with transaction.atomic():
            for name, (cfg, service_type) in resolved.items():
                cluster, created = ServiceCluster.objects.get_or_create(
                    name=name,
                    defaults={"service_type": service_type},
                )
                if not created and cluster.service_type_id != service_type.pk:
                    cluster.service_type = service_type
                    cluster.save(update_fields=["service_type"])

                self.stdout.write(f"{'Created' if created else 'Updated'} cluster '{name}' (type={cfg['type']})")

                self._sync_nodes(cluster, name, cfg.get("nodes", []))

                ServiceAPIRoute.objects.update_or_create(
                    service_cluster=cluster,
                    defaults={
                        "name": f"{name} api",
                        "api_slug": cfg["api_slug"],
                        "service_port": cfg["service_port"],
                        "service_path": cfg["service_path"],
                        "is_service_https": cfg.get("is_service_https", False),
                    },
                )

    def _sync_nodes(self, cluster, service_name, nodes):
        """Diffs the desired node list against the DB and applies only the delta.

        Existing nodes whose address appears in the config are left untouched.
        Nodes removed from the config are deleted. New addresses are created.
        This avoids unnecessary churn on audit logs or FK-referencing systems.

        Args:
            cluster: The ServiceCluster to sync nodes for.
            service_name: Used to build the node name on creation.
            nodes: List of node dicts from the YAML config, each with an 'address' key.
        """
        existing = set(ServiceNode.objects.filter(service_cluster=cluster).values_list("address", flat=True))
        desired = {node["address"] for node in nodes}

        removed = existing - desired
        if removed:
            ServiceNode.objects.filter(service_cluster=cluster, address__in=removed).delete()

        for node in nodes:
            if node["address"] not in existing:
                ServiceNode.objects.create(
                    name=f"Node {service_name} - {node['address']}",
                    service_cluster=cluster,
                    address=node["address"],
                )
