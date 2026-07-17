import yaml
from django.core.management.base import BaseCommand, CommandError

from aap_gateway_api.models import ServiceAPIRoute, ServiceCluster, ServiceNode, ServiceType
from aap_gateway_api.utils.service_id_sync import populate_missing_service_ids


class Command(BaseCommand):
    """Sync service IDs for registered clusters and optionally register new services.

    Without --register: populates service_id on every cluster where it is null.
    With --register <config.yml>: upserts service definitions from a YAML config file,
    then populates service_id for any cluster (including newly created ones) that lacks one.
    With --force: re-fetches and overwrites service_id even for clusters that already have one.

    Safe to run on every upgrade.

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
            "--username",
            type=str,
            default=None,
            help="Gateway username for API requests. Defaults to the first superuser.",
        )
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

        Args:
            *args: Unused positional arguments.
            **options: Parsed command options (username, register, force).
        """
        user = self._resolve_user(options["username"])

        if options["register"]:
            self._register_from_config(options["register"])

        populated, failed = populate_missing_service_ids(user=user, force=options["force"])

        if not populated and not failed:
            self.stdout.write("No clusters with missing service_id found.")
            return

        if populated:
            self.stdout.write(self.style.SUCCESS(f"Populated: {', '.join(populated)}"))
        if failed:
            self.stderr.write(self.style.WARNING(f"Failed: {', '.join(failed)}"))

    def _resolve_user(self, username):
        """Returns the User for the given username, or None to use the default superuser.

        Args:
            username: The username string, or None.

        Returns:
            User instance, or None if username was not provided.

        Raises:
            CommandError: If username is provided but does not exist in the database.
        """
        if not username:
            return None
        from aap_gateway_api.models import User

        try:
            return User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"User '{username}' does not exist.")

    def _register_from_config(self, config_path):
        """Reads a YAML config and upserts ServiceCluster, ServiceNode, and ServiceAPIRoute records.

        Nodes for each cluster are replaced on every run (delete + recreate) to reflect the
        current config. The ServiceAPIRoute is created or updated via update_or_create so that
        changes to port or path are applied without duplication.

        Args:
            config_path: Filesystem path to the YAML config file.

        Raises:
            CommandError: If the file is missing, not valid YAML, lacks a 'services' key,
                or references an unknown ServiceType.
        """
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
        except FileNotFoundError:
            raise CommandError(f"{config_path} does not exist.")

        if not isinstance(config, dict) or "services" not in config:
            raise CommandError(f"{config_path} must be a YAML mapping with a 'services' key.")

        for name, cfg in config["services"].items():
            service_type = ServiceType.objects.filter(name=cfg["type"]).first()
            if service_type is None:
                raise CommandError(f"Unknown service type '{cfg['type']}' for '{name}'. Allowed: {list(ServiceType.objects.values_list('name', flat=True))}")

            cluster, _ = ServiceCluster.objects.get_or_create(name=name, service_type=service_type)
            self.stdout.write(f"Registered cluster '{name}' (type={cfg['type']})")

            ServiceNode.objects.filter(service_cluster=cluster).delete()
            for node in cfg.get("nodes", []):
                ServiceNode.objects.create(
                    name=f"Node {name} - {node['address']}",
                    service_cluster=cluster,
                    address=node["address"],
                )

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
