"""Regenerate openapi.yaml from the current code using drf-spectacular."""

import os
import re

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "aap_gateway_api.settings")
django.setup()

from django.conf import settings  # noqa: E402
from django.core.management import call_command  # noqa: E402

db = settings.DATABASES["default"]
db["ENGINE"] = "django.db.backends.sqlite3"
db["NAME"] = ":memory:"
db["OPTIONS"] = {}
call_command("migrate", "--run-syncdb", verbosity=0)
call_command("spectacular", "--format", "openapi", "--file", "openapi.yaml")


def _stabilize_yaml(path):
    """Sort enum arrays and description enum lines for deterministic output.

    drf-spectacular emits enum values in non-deterministic order due to
    Python set iteration in authenticator plugin discovery. This function
    post-processes the generated YAML text to sort those blocks without
    disturbing the rest of the file formatting.
    """
    with open(path) as f:
        lines = f.readlines()

    # Sort YAML enum blocks: "enum:" followed by "- value" lines
    i = 0
    while i < len(lines):
        stripped = lines[i].rstrip()
        if stripped.endswith("enum:") and not stripped.endswith("x-spec-enum-id:"):
            indent = len(lines[i]) - len(lines[i].lstrip())
            item_indent = indent + 2
            j = i + 1
            enum_items = []
            while j < len(lines):
                line = lines[j]
                if line.rstrip() == "":
                    break
                cur_indent = len(line) - len(line.lstrip())
                if cur_indent == item_indent and line.lstrip().startswith("- "):
                    enum_items.append(line)
                    j += 1
                else:
                    break
            if enum_items:
                enum_items.sort()
                lines[i + 1 : j] = enum_items
                i = i + 1 + len(enum_items)
            else:
                i += 1
        else:
            i += 1

    # Sort description enum lines: "* `value` - label"
    enum_line_re = re.compile(r"^(\s+)\* `([^`]+)` - ")
    i = 0
    while i < len(lines):
        m = enum_line_re.match(lines[i])
        if m:
            j = i
            block = []
            while j < len(lines) and enum_line_re.match(lines[j]):
                block.append(lines[j])
                j += 1
            if len(block) > 1:
                block.sort(key=lambda l: enum_line_re.match(l).group(2))
                lines[i:j] = block
            i += len(block)
        else:
            i += 1

    with open(path, "w") as f:
        f.writelines(lines)


_stabilize_yaml("openapi.yaml")
