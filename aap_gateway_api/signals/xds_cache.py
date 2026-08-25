from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from aap_gateway_api.models.additional_route import AdditionalRoute
from aap_gateway_api.models.ca_certificate import CACertificate
from aap_gateway_api.models.http_port import HTTPPort
from aap_gateway_api.models.route import Route
from aap_gateway_api.models.service_api_route import ServiceAPIRoute
from aap_gateway_api.models.service_cluster import ServiceCluster
from aap_gateway_api.models.service_node import ServiceNode
from aap_gateway_api.models.ui_plugin_route import UIPluginRoute
from aap_gateway_api.views.api.envoy.rest_control_plane import XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS, XDS_CACHE_KEY_SDS, invalidate_xds_cache


@receiver(post_save, sender=Route)
@receiver(post_delete, sender=Route)
@receiver(post_save, sender=AdditionalRoute)
@receiver(post_delete, sender=AdditionalRoute)
@receiver(post_save, sender=ServiceAPIRoute)
@receiver(post_delete, sender=ServiceAPIRoute)
@receiver(post_save, sender=UIPluginRoute)
@receiver(post_delete, sender=UIPluginRoute)
def _invalidate_on_route_change(sender, **kwargs):
    transaction.on_commit(lambda: invalidate_xds_cache(XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS))


@receiver(post_save, sender=HTTPPort)
@receiver(post_delete, sender=HTTPPort)
def _invalidate_on_http_port_change(sender, **kwargs):
    transaction.on_commit(lambda: invalidate_xds_cache(XDS_CACHE_KEY_LDS))


@receiver(post_save, sender=ServiceCluster)
@receiver(post_delete, sender=ServiceCluster)
def _invalidate_on_service_cluster_change(sender, **kwargs):
    transaction.on_commit(lambda: invalidate_xds_cache(XDS_CACHE_KEY_CDS, XDS_CACHE_KEY_LDS))


@receiver(post_save, sender=ServiceNode)
@receiver(post_delete, sender=ServiceNode)
def _invalidate_on_service_node_change(sender, **kwargs):
    transaction.on_commit(lambda: invalidate_xds_cache(XDS_CACHE_KEY_CDS))


@receiver(post_save, sender=CACertificate)
@receiver(post_delete, sender=CACertificate)
def _invalidate_on_ca_certificate_change(sender, **kwargs):
    transaction.on_commit(lambda: invalidate_xds_cache(XDS_CACHE_KEY_SDS))
