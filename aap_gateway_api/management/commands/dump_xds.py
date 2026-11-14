"""Dump the xDS resources the control plane would deliver to Envoy."""

import json

from django.core.management.base import BaseCommand
from google.protobuf.json_format import MessageToDict

from aap_gateway_api.utils.xds_resources import collect_clusters, collect_listeners, collect_secrets

COLLECTORS = {
    "cds": collect_clusters,
    "lds": collect_listeners,
    "sds": collect_secrets,
}


class Command(BaseCommand):
    help = "Dump the xDS resources (CDS/LDS/SDS) the control plane would deliver, as JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--type",
            action="append",
            dest="types",
            choices=sorted(COLLECTORS),
            help="Resource type(s) to dump (repeatable). Defaults to all.",
        )

    def handle(self, *args, **options):
        types = options["types"] or list(COLLECTORS)
        data = {}
        for kind in types:
            resource_set = COLLECTORS[kind]()
            data[kind] = {
                "version": resource_set.version,
                "resources": [MessageToDict(r) for r in resource_set.resources],
            }
        self.stdout.write(json.dumps(data, indent=2))
