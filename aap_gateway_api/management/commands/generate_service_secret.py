from django.core.management.base import BaseCommand

from aap_gateway_api.models.service import ServiceAPIRoute, ServiceCluster


class Command(BaseCommand):
    help = "Generate a new secret key for a service."

    def add_arguments(self, parser):
        services = ServiceAPIRoute.objects.exclude(service_cluster__service_type=ServiceCluster.ServiceType.GATEWAY).values_list("api_slug", flat=True)
        parser.add_argument(
            "api-slug",
            type=str,
            help="API slug for service you wish to generate a key for.",
            choices=services,
        )

    def handle(self, *args, **options):
        cluster = ServiceAPIRoute.objects.get(api_slug=options["api-slug"]).service_cluster
        new_key = cluster.generate_key()
        self.stdout.write(new_key.secret)
