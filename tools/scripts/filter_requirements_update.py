#!/usr/bin/env python3
"""Restrict a regenerated requirements file to one package's updates.

Given the current and newly resolved requirements files, keep the new
version of the named package and its transitive dependencies while
restoring every other package from the current file.
"""

import argparse
import re
import sys
from pathlib import Path

PACKAGE_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def canonicalize_name(name):
    """Normalize a package name per PEP 503."""
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def parse_blocks(text):
    """Split a compiled requirements file into all lines for each canonical package name."""
    blocks = {}
    current = []
    for line in text.splitlines(keepends=True):
        if line[:1].isspace() or line.startswith("#") or not line.strip():
            if current:
                current.append(line)
            continue
        if current:
            _store_block(blocks, current)
        current = [line]
    if current:
        _store_block(blocks, current)
    return blocks


def _store_block(blocks, lines):
    while lines and not lines[-1].strip():
        lines.pop()
    match = PACKAGE_RE.match(lines[0])
    if match:
        blocks.setdefault(canonicalize_name(match.group(1)), []).extend(lines)


def via_parents(lines):
    """Return the packages that depend on the block's package."""
    parents = []
    in_via = False
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped.startswith("#"):
            in_via = False
            continue
        comment = stripped[1:].strip()
        if comment == "via":
            in_via = True
        elif comment.startswith("via "):
            parents.append(comment[4:].strip())
        elif in_via and comment and not comment.startswith("-"):
            parents.append(comment.split()[0])
    return parents


def dependency_graph(blocks):
    """Map each package to the packages it depends on."""
    graph = {name: set() for name in blocks}
    for name, lines in blocks.items():
        for parent in via_parents(lines):
            graph.setdefault(canonicalize_name(parent), set()).add(name)
    return graph


def transitive_dependencies(graph, package):
    """Return package plus everything it transitively depends on."""
    seen = {package}
    pending = [package]
    while pending:
        for child in graph.get(pending.pop(), ()):
            if child not in seen:
                seen.add(child)
                pending.append(child)
    return seen


def filter_update(current_text, resolved_text, package):
    """Merge resolved updates for package and its dependencies into current."""
    current = parse_blocks(current_text)
    resolved = parse_blocks(resolved_text)
    package = canonicalize_name(package)
    current_graph = dependency_graph(current)
    resolved_graph = dependency_graph(resolved)

    if package not in resolved_graph:
        raise ValueError(f"package {package!r} not found in resolved requirements")

    updated = transitive_dependencies(resolved_graph, package)
    updated |= transitive_dependencies(current_graph, package)

    # Follow resolved edges from every package selected for replacement,
    # including ones retained from the current graph, so dependencies newly
    # introduced by the replacement are not omitted from the merged file.
    pending = list(updated)
    while pending:
        for dependency in resolved_graph.get(pending.pop(), ()):
            if dependency not in updated:
                updated.add(dependency)
                pending.append(dependency)

    merged = dict(current)
    for name in updated:
        if name in resolved:
            merged[name] = resolved[name]
        else:
            merged.pop(name, None)

    return "".join("".join(merged[name]) for name in sorted(merged))


def main(argv=None):
    """Write the filtered requirements file to the requested output path."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("current", type=Path, help="Current requirements file")
    parser.add_argument("resolved", type=Path, help="Newly resolved requirements file")
    parser.add_argument("package", help="Package whose updates to preserve")
    parser.add_argument("output", type=Path, help="File to write the merged result to")
    args = parser.parse_args(argv)

    try:
        result = filter_update(
            args.current.read_text(),
            args.resolved.read_text(),
            args.package,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    args.output.write_text(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
