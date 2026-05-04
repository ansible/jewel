import logging

from dispatcherd import run_service as run_dispatcherd_service
from dispatcherd.config import setup as dispatcherd_setup
from django.core.management.base import BaseCommand

from aap_gateway_api.dispatch.config import get_dispatcherd_config

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the dispatcherd background task service"

    def handle(self, *args, **options):
        config = get_dispatcherd_config()
        dispatcherd_setup(config)

        verbosity = options.get("verbosity", 1)
        if verbosity >= 1:
            self.stdout.write(self.style.SUCCESS("Starting dispatcherd service."))

        logger.info("Starting dispatcherd service.")

        try:
            run_dispatcherd_service()
        except KeyboardInterrupt:
            self.stdout.write("dispatcherd shutdown requested.")
            logger.info("dispatcherd shutdown requested.")
