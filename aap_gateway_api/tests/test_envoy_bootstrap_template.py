"""Guard rails for the dev Envoy bootstrap template (tools/ansible/roles/proxy-config)."""

import re
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[2] / "tools/ansible/roles/proxy-config/templates/envoy.yml.j2"


def standalone_jinja_comment_lines(text: str) -> list[int]:
    return [number for number, line in enumerate(text.splitlines(), 1) if re.match(r"\s*\{#", line)]


def test_template_has_no_standalone_jinja_comment_lines():
    # Ansible renders templates with trim_blocks=True, which swallows the
    # newline after a `{# ... #}` comment and glues the comment line's
    # indentation onto the next line.  In this YAML that shifts a list item out
    # of alignment with its keys (Envoy: "end of map not found").  Use a plain
    # YAML `#` comment instead.
    assert standalone_jinja_comment_lines(TEMPLATE.read_text()) == []


def test_guard_detects_the_broken_pattern():
    broken = "static_resources:\n  clusters:\n  {# note #}\n  - type: STRICT_DNS\n"
    assert standalone_jinja_comment_lines(broken) == [3]
