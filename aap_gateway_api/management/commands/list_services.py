from django.core.management.base import BaseCommand

from aap_gateway_api.models.service import AdditionalRoute, ServiceAPIRoute, ServiceCluster, ServiceNode


class Command(BaseCommand):
    help = "List all clusters, nodes and routes."

    def handle(self, *args, **options):
        # display each of the these route properties
        route_props = [
            'http_port',
            'gateway_path',
            'enable_gateway_auth',
            'is_service_https',
            'service_port',
            'service_path',
            'serviceapiroute',
            'api_slug',
        ]

        # iterate through service clusters
        for cluster in ServiceCluster.objects.all():
            self.stdout.write(f'\ncluster: {cluster}')

            # print out all the nodes in the cluster
            for node in ServiceNode.objects.filter(service_cluster=cluster):
                self.stdout.write(f'\tnode: {node}')

            # iterate through route types
            for qs in [ServiceAPIRoute, AdditionalRoute]:
                for route in qs.objects.filter(service_cluster=cluster):
                    self.stdout.write(f'\t{qs.__name__}: {route.name}')
                    for rprop in route_props:
                        # "additional routes" don't have all the same props
                        if hasattr(route, rprop):
                            val = getattr(route, rprop)
                            self.stdout.write(f'\t\t{rprop}: {val}')
