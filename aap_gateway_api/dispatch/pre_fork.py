import django
from django.core.cache import cache
from django.db import connections

django.setup()

cache.close()
connections.close_all()
