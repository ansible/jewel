import logging
import multiprocessing
import os
import sys
from concurrent import futures

import grpc
from ansible_base.observability import setup_observability
from django.conf import settings
from django.core.management.base import BaseCommand
from envoy.service.auth.v3 import external_auth_pb2_grpc
from envoy.service.discovery.v3 import ads_pb2_grpc

from aap_gateway_api.proxy.ads import AggregatedDiscoveryService, StreamRegistry
from aap_gateway_api.proxy.control_plane import ExternalAuth
from aap_gateway_api.proxy.xds_watcher import XDSWatcher

logger = logging.getLogger('aap.gateway.proxy.control_plane')

_MAX_RECEIVE_MESSAGE_LENGTH = settings.GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH
_PORT = settings.GRPC_SERVER_PORT

# Set verbosity for GRPC to ERROR (unless overridden in settings) to prevent log spam with:
# fork_posix.cc:75] Other threads are currently calling into gRPC, skipping fork() handlers
os.environ["GRPC_VERBOSITY"] = getattr(settings, "GRPC_VERBOSITY", "ERROR")


def _run_server(bind_address, debug):
    setup_observability(service_name="gateway-grpc")
    if debug:
        # Single process, but at least 2 threads: an ADS stream holds its
        # worker thread for the stream's lifetime, so a single thread would
        # let one connected Envoy starve every ext_authz check.
        _THREAD_CONCURRENCY = 2
        try:
            import debugpy

            debugpy.listen(("0.0.0.0", 3001))
        except ImportError:
            print("Unable to import debugpy, please install it")
            raise
    else:
        _THREAD_CONCURRENCY = settings.GRPC_SERVER_MAX_THREADS_PER_PROCESS

    """Start a server in a subprocess."""
    logger.info("Starting gRPC worker process.")
    options = (("grpc.so_reuseport", 1), ("grpc.max_receive_message_length", _MAX_RECEIVE_MESSAGE_LENGTH))

    server = grpc.server(
        futures.ThreadPoolExecutor(
            max_workers=_THREAD_CONCURRENCY,
        ),
        options=options,
    )
    external_auth_pb2_grpc.add_AuthorizationServicer_to_server(ExternalAuth(), server)

    # Each worker process gets its own registry and watcher; the watchers
    # converge via the shared cache's digests.
    registry = StreamRegistry()
    ads_pb2_grpc.add_AggregatedDiscoveryServiceServicer_to_server(AggregatedDiscoveryService(registry), server)
    watcher = XDSWatcher(registry)

    server.add_insecure_port(bind_address)
    server.start()
    watcher.start()
    server.wait_for_termination()


class Command(BaseCommand):
    help = "Launch gRPC auth service for envoy."

    def add_arguments(self, parser):
        parser.add_argument('--debug', action='store_true', help='Run GRPC in debug mode (single process)')

    def handle(self, *args, **options):
        if options['debug']:
            _PROCESS_COUNT = 1
        else:
            _PROCESS_COUNT = settings.GRPC_SERVER_PROCESSES

        bind_address = "[::]:" + _PORT
        logger.info("Binding to '%s'", bind_address)
        sys.stdout.flush()
        workers = []
        for _ in range(_PROCESS_COUNT):
            # NOTE: It is imperative that the worker subprocesses be forked before
            # any gRPC servers start up. See
            # https://github.com/grpc/grpc/issues/16001 for more details.
            worker = multiprocessing.Process(target=_run_server, args=(bind_address, options['debug']))
            worker.start()
            workers.append(worker)
        for worker in workers:
            worker.join()
