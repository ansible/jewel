import django
from django.core.cache import cache
from django.db import connection

django.setup()

cache.close()
connection.close()
