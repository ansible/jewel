from django.core.management.base import BaseCommand

from aap_gateway_api.models import AdditionalRoute, ServiceAPIRoute, ServiceCluster, ServiceNode


class Command(BaseCommand):
    help = "List all clusters, nodes and routes."
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

    def handle(self, *args, **options):
        """
        print all nodes for a given cluster and
        display each of the route property in self.route_props
        """

        # iterate through service clusters
        for cluster in ServiceCluster.objects.all():
            self.stdout.write(f'\ncluster: {cluster}')
            self._print_nodes_in_cluster(cluster)
            self._print_routes_in_cluster(cluster)

    def _print_nodes_in_cluster(self, cluster):
        """
        print all nodes for a given cluster.
        """
        for node in ServiceNode.objects.filter(service_cluster=cluster):
            self.stdout.write(f"\tnode: {node}")

    def _print_routes_in_cluster(self, cluster):
        """
        print all API and additional routes and their properties.
        """
        # iterate through route types
        for qs in [ServiceAPIRoute, AdditionalRoute]:
            for route in qs.objects.filter(service_cluster=cluster):
                self.stdout.write(f'\t{qs.__name__}: {route.name}')
                for rprop in self.route_props:
                    # "additional routes" don't have all the same props
                    if hasattr(route, rprop):
                        val = getattr(route, rprop)
                        self.stdout.write(f'\t\t{rprop}: {val}')
