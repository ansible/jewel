"""Regenerate openapi.yaml from the current code using drf-spectacular."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "aap_gateway_api.settings")
django.setup()

from django.conf import settings  # noqa: E402
from django.core.management import call_command  # noqa: E402

settings.DATABASES["default"]["OPTIONS"] = {}
call_command("migrate", "--run-syncdb", verbosity=0)
call_command("spectacular", "--format", "openapi", "--file", "openapi.yaml")
