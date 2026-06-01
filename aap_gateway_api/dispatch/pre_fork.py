import django
from django.core.cache import cache
from django.db import connections

django.setup()

import aap_gateway_api.tasks.cache  # noqa: F401, E402 — register dispatcherd task

cache.close()
connections.close_all()
