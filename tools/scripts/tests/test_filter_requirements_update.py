"""Tests for filter_requirements_update.py."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from filter_requirements_update import filter_update  # noqa: E402


def make_block(name, version, via=None):
    lines = [f"{name}=={version} \\\n", "    --hash=sha256:deadbeef\n"]
    if via:
        if len(via) == 1:
            lines.append(f"    # via {via[0]}\n")
        else:
            lines.append("    # via\n")
            lines.extend(f"    #   {parent}\n" for parent in via)
    return "".join(lines)


def test_restores_unrelated_packages():
    current = make_block("a", "1") + make_block("d", "1", ["-r requirements.in"])
    resolved = make_block("a", "2") + make_block("d", "2", ["-r requirements.in"])

    assert filter_update(current, resolved, "a") == (make_block("a", "2") + make_block("d", "1", ["-r requirements.in"]))


def test_preserves_transitive_dependencies():
    current = make_block("a", "1") + make_block("b", "1", ["a"]) + make_block("c", "1", ["b"]) + make_block("d", "1", ["-r requirements.in"])
    resolved = make_block("a", "2") + make_block("b", "2", ["a"]) + make_block("c", "2", ["b"]) + make_block("d", "2", ["-r requirements.in"])

    assert filter_update(current, resolved, "a") == (
        make_block("a", "2") + make_block("b", "2", ["a"]) + make_block("c", "2", ["b"]) + make_block("d", "1", ["-r requirements.in"])
    )


def test_removes_dependencies_dropped_by_update():
    current = make_block("a", "1") + make_block("b", "1", ["a"])
    resolved = make_block("a", "2")

    assert filter_update(current, resolved, "a") == make_block("a", "2")


def test_adds_new_transitive_dependencies():
    current = make_block("a", "1")
    resolved = make_block("a", "2") + make_block("b", "2", ["a"])

    assert filter_update(current, resolved, "a") == (make_block("a", "2") + make_block("b", "2", ["a"]))


def test_does_not_add_unrelated_new_packages():
    current = make_block("a", "1")
    resolved = make_block("a", "2") + make_block("z", "2", ["-r requirements.in"])

    assert filter_update(current, resolved, "a") == make_block("a", "2")


def test_missing_package_raises():
    with pytest.raises(ValueError, match="not found"):
        filter_update(make_block("a", "1"), make_block("a", "2"), "missing")


@pytest.mark.parametrize("package", ["foo-bar", "Foo_Bar", "FOO.BAR"])
def test_package_name_is_normalized(package):
    current = make_block("foo-bar", "1")
    resolved = make_block("foo-bar", "2")

    assert filter_update(current, resolved, package) == make_block("foo-bar", "2")
