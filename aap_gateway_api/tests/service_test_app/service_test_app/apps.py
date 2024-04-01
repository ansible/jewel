import logging
import os

from django.apps import AppConfig
from django.core.management.sql import emit_post_migrate_signal
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor
from django.utils.module_loading import import_string

logger = logging.getLogger("service_test_app")
logging.basicConfig(level=logging.INFO)


class AapConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'service_test_app'

    def migration_callback(self, *args):
        str_args = [str(arg) for arg in args]
        logger.info(" ".join(str_args))

    def ready(self) -> None:
        # Migrate the in memory database. This has to run on every startup because the
        # database is not persistent. We're not using the django migrate command because
        # that gets executed in another thread.
        con = connections[DEFAULT_DB_ALIAS]
        executor = MigrationExecutor(con, progress_callback=self.migration_callback)
        executor.migrate(executor.loader.graph.leaf_nodes())

        emit_post_migrate_signal(
            1,
            False,
            con.alias,
        )

        # Set up any test data that is requested.
        from service_test_app.models import User

        User.objects.create(username="_system")

        if fixture := os.environ.get("SERVICE_TEST_APP_FIXTURE"):
            logger.info("loading fixture " + fixture)
            setup_func = import_string("fixtures." + fixture + ".setup")
            setup_func()
        else:
            logger.info("No fixture specified.")
