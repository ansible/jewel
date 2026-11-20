"""Regenerate openapi.yaml from the current code using drf-spectacular."""

import os
import re
import sys
import types

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "aap_gateway_api.settings")
django.setup()

from django.conf import settings  # noqa: E402
from django.core.management import call_command  # noqa: E402

_ENUM_LINE = re.compile(r"^\s*\*\s*`")


def sort_enums(result, generator, **kwargs):
    """Sort enum arrays and their description lists for deterministic output."""

    def _walk(obj):
        if isinstance(obj, dict):
            if "enum" in obj and isinstance(obj["enum"], list):
                try:
                    obj["enum"].sort()
                except TypeError:
                    pass
                if "description" in obj and isinstance(obj["description"], str):
                    _sort_desc(obj)
            for val in obj.values():
                _walk(val)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    def _sort_desc(obj):
        lines = obj["description"].split("\n")
        i = 0
        while i < len(lines):
            if _ENUM_LINE.match(lines[i]):
                j = i
                while j < len(lines) and _ENUM_LINE.match(lines[j]):
                    j += 1
                lines[i:j] = sorted(lines[i:j])
                i = j
            else:
                i += 1
        obj["description"] = "\n".join(lines)

    _walk(result)
    return result


_hooks_mod = types.ModuleType("_genschema_hooks")
_hooks_mod.sort_enums = sort_enums
sys.modules["_genschema_hooks"] = _hooks_mod

db = settings.DATABASES["default"]
db["ENGINE"] = "django.db.backends.sqlite3"
db["NAME"] = ":memory:"
db["OPTIONS"] = {}

spectacular = {**getattr(settings, "SPECTACULAR_SETTINGS", {})}
hooks = list(spectacular.get("POSTPROCESSING_HOOKS", [
    "drf_spectacular.hooks.postprocess_schema_enums",
]))
hooks.append("_genschema_hooks.sort_enums")
spectacular["POSTPROCESSING_HOOKS"] = hooks
settings.SPECTACULAR_SETTINGS = spectacular

call_command("migrate", "--run-syncdb", verbosity=0)
call_command("spectacular", "--format", "openapi", "--file", "openapi.yaml")
