from django.core.management.base import BaseCommand, CommandError

from aap_gateway_api.utils.service_id_sync import populate_missing_service_ids


class Command(BaseCommand):
    """Populate service_id for any registered service clusters that are missing one.

    Fetches each service's metadata endpoint to obtain its service_id and writes
    it to the ServiceCluster record. Safe to run on every upgrade.

    Invoke via::

        aap-gateway-manage sync_service_ids
        aap-gateway-manage sync_service_ids --force
    """

    help = "Populate service_id for registered service clusters that are missing one."

    def add_arguments(self, parser):
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
        """Fetches and writes service_id for all clusters that need one.

        Args:
            *args: Unused positional arguments.
            **options: Parsed command options (force).
        """
        populated, failed = populate_missing_service_ids(force=options["force"])

        if not populated and not failed:
            self.stdout.write("No clusters with missing service_id found.")
            return

        if populated:
            self.stdout.write(self.style.SUCCESS(f"Populated: {', '.join(populated)}"))
        if failed:
            self.stderr.write(self.style.WARNING(f"Failed: {', '.join(failed)}"))
            raise CommandError(f"Failed to populate service_id for {len(failed)} cluster(s): {', '.join(failed)}")
