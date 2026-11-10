"""Tests for filter_requirements_update.py."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from filter_requirements_update import filter_update, main  # noqa: E402


def make_block(name, version, via=None, marker=None):
    """Build a compiled requirements block for tests."""
    spec = f"{name}=={version}"
    if marker:
        spec = f"{spec} ; {marker}"
    lines = [f"{spec} \\\n", "    --hash=sha256:deadbeef\n"]
    if via:
        if len(via) == 1:
            lines.append(f"    # via {via[0]}\n")
        else:
            lines.append("    # via\n")
            lines.extend(f"    #   {parent}\n" for parent in via)
    return "".join(lines)


def test_restores_unrelated_packages():
    """Unrelated packages retain their current versions."""
    current = make_block("a", "1") + make_block("d", "1", ["-r requirements.in"])
    resolved = make_block("a", "2") + make_block("d", "2", ["-r requirements.in"])

    assert filter_update(current, resolved, "a") == (make_block("a", "2") + make_block("d", "1", ["-r requirements.in"]))


def test_preserves_transitive_dependencies():
    """Transitive dependencies shared by multiple parents are retained."""
    current = make_block("a", "1") + make_block("b", "1", ["d", "a"]) + make_block("c", "1", ["b"]) + make_block("d", "1", ["-r requirements.in"])
    resolved = make_block("a", "2") + make_block("b", "2", ["d", "a"]) + make_block("c", "2", ["b"]) + make_block("d", "2", ["-r requirements.in"])

    assert filter_update(current, resolved, "a") == (
        make_block("a", "2") + make_block("b", "2", ["d", "a"]) + make_block("c", "2", ["b"]) + make_block("d", "1", ["-r requirements.in"])
    )


def test_removes_dependencies_dropped_by_update():
    """Dependencies no longer present after resolution are removed."""
    current = make_block("a", "1") + make_block("b", "1", ["a"])
    resolved = make_block("a", "2")

    assert filter_update(current, resolved, "a") == make_block("a", "2")


def test_adds_new_transitive_dependencies():
    """New dependencies of the selected package are added."""
    current = make_block("a", "1")
    resolved = make_block("a", "2") + make_block("b", "2", ["a"])

    assert filter_update(current, resolved, "a") == (make_block("a", "2") + make_block("b", "2", ["a"]))


def test_does_not_add_unrelated_new_packages():
    """New packages unrelated to the selected package are ignored."""
    current = make_block("a", "1")
    resolved = make_block("a", "2") + make_block("z", "2", ["-r requirements.in"])

    assert filter_update(current, resolved, "a") == make_block("a", "2")


def test_missing_package_raises():
    """An unknown package name is rejected."""
    with pytest.raises(ValueError, match="not found"):
        filter_update(make_block("a", "1"), make_block("a", "2"), "missing")


@pytest.mark.parametrize("package", ["foo-bar", "Foo_Bar", "FOO.BAR"])
def test_package_name_is_normalized(package):
    """Package names are canonicalized before lookup."""
    current = make_block("foo-bar", "1")
    resolved = make_block("foo-bar", "2")

    assert filter_update(current, resolved, package) == make_block("foo-bar", "2")


@pytest.mark.parametrize("selected", [False, True])
def test_preserves_all_marker_qualified_blocks(selected):
    """Marker-qualified pins for selected and restored packages are not overwritten."""
    low_marker = 'python_version < "3.11"'
    high_marker = 'python_version >= "3.11"'
    current = make_block("a", "1") + make_block("b", "1", marker=low_marker) + make_block("b", "1", marker=high_marker)
    resolved = make_block("a", "2") + make_block("b", "2", marker=low_marker) + make_block("b", "2", marker=high_marker)
    expected_a_version = "1" if selected else "2"
    expected_b_version = "2" if selected else "1"

    assert filter_update(current, resolved, "b" if selected else "a") == (
        make_block("a", expected_a_version) + make_block("b", expected_b_version, marker=low_marker) + make_block("b", expected_b_version, marker=high_marker)
    )


def test_skips_empty_dependency_comments():
    """An empty comment in a multiline via annotation does not abort filtering."""
    current = make_block("a", "1") + "b==1 \\\n    --hash=sha256:deadbeef\n    # via\n    #\n    #   a\n"
    resolved = make_block("a", "2") + "b==2 \\\n    --hash=sha256:deadbeef\n    # via\n    #\n    #   a\n"

    assert filter_update(current, resolved, "a") == (make_block("a", "2") + "b==2 \\\n    --hash=sha256:deadbeef\n    # via\n    #\n    #   a\n")


def test_includes_dependencies_of_replaced_retained_packages():
    """A retained dependency replaced through the selected package gains its new dependency."""
    current = make_block("a", "1") + make_block("b", "1", ["a", "d"]) + make_block("d", "1", ["-r requirements.in"])
    resolved = make_block("a", "2") + make_block("b", "2", ["d"]) + make_block("c", "2", ["b"]) + make_block("d", "1", ["-r requirements.in"])

    assert filter_update(current, resolved, "a") == (
        make_block("a", "2") + make_block("b", "2", ["d"]) + make_block("c", "2", ["b"]) + make_block("d", "1", ["-r requirements.in"])
    )


def test_allows_non_emitted_package_as_dependency_root():
    """A package omitted from resolved output can still select its dependencies."""
    current = make_block("a", "1", ["django-ansible-base"])
    resolved = make_block("a", "2", ["django-ansible-base"])

    assert filter_update(current, resolved, "django-ansible-base") == make_block("a", "2", ["django-ansible-base"])


def test_ignores_trailing_blank_lines():
    """Trailing blank lines in compiled blocks are ignored."""
    current = make_block("a", "1") + "\n"
    resolved = make_block("a", "2") + "\n"

    assert filter_update(current, resolved, "a") == make_block("a", "2")


def test_main_writes_output(tmp_path):
    """The command-line entry point writes the merged requirements file."""
    current = tmp_path / "current.txt"
    resolved = tmp_path / "resolved.txt"
    output = tmp_path / "output.txt"
    current.write_text(make_block("a", "1"))
    resolved.write_text(make_block("a", "2"))

    assert main([str(current), str(resolved), "a", str(output)]) == 0
    assert output.read_text() == make_block("a", "2")


def test_main_reports_missing_package(tmp_path, capsys):
    """The command-line entry point reports an unknown package without writing output."""
    current = tmp_path / "current.txt"
    resolved = tmp_path / "resolved.txt"
    output = tmp_path / "output.txt"
    current.write_text(make_block("a", "1"))
    resolved.write_text(make_block("a", "2"))

    assert main([str(current), str(resolved), "missing", str(output)]) == 1
    assert not output.exists()
    assert "package 'missing' not found" in capsys.readouterr().err
