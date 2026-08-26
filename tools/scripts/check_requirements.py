#!/usr/bin/env python3
"""Verify that requirements.txt satisfies all constraints from gateway and DAB requirements."""

import re
import sys
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version


def parse_pinned(path):
    """Parse pinned versions from a compiled requirements.txt (package==version)."""
    pins = {}
    for line in Path(path).read_text().splitlines():
        m = re.match(r'^([a-zA-Z0-9_.-]+)(?:\[[^\]]*\])?==([^\s\\]+)', line)
        if m:
            pins[m.group(1).lower().replace('-', '_')] = Version(m.group(2))
    return pins


def parse_constraints(path):
    """Parse package constraints from a .in file, skipping comments and blank lines."""
    constraints = []
    for line in Path(path).read_text().splitlines():
        line = line.split('#')[0].strip()
        if not line or line.startswith('-'):
            continue
        try:
            constraints.append(Requirement(line))
        except Exception as exc:
            print(f"WARNING: skipping unparseable line in {path}: {line!r} ({exc})", file=sys.stderr)
            continue
    return constraints


def parse_dab_extras(requirements_git_path):
    """Extract the extras list from requirements_git.txt (e.g. [extra1,extra2,...])."""
    text = requirements_git_path.read_text()
    m = re.search(r'django-ansible-base\[([^\]]+)\]', text)
    if not m:
        return []
    return [e.strip().replace('-', '_') for e in m.group(1).split(',')]


def find_dab_constraint_files(req_dir, extras):
    """Find DAB requirements .in files for the given extras."""
    dab_dir = req_dir.parent / 'django-ansible-base' / 'requirements'
    if not dab_dir.is_dir():
        return []

    files = [dab_dir / 'requirements.in']
    for extra in extras:
        files.append(dab_dir / f'requirements_{extra}.in')

    return [f for f in files if f.exists()]


def main():
    req_dir = Path(__file__).resolve().parent.parent.parent / 'requirements'
    pins = parse_pinned(req_dir / 'requirements.txt')

    input_files = [
        req_dir / 'requirements.in',
    ]

    requirements_git = req_dir / 'requirements_git.txt'
    if requirements_git.exists():
        extras = parse_dab_extras(requirements_git)
        dab_files = find_dab_constraint_files(req_dir, extras)
        if dab_files:
            input_files.extend(dab_files)
            print(f"Including {len(dab_files)} DAB requirements file(s)", file=sys.stderr)
        else:
            print("WARNING: django-ansible-base not checked out, skipping DAB constraints", file=sys.stderr)

    constraints = []
    for path in input_files:
        constraints.extend(parse_constraints(path))

    errors = []
    for req in constraints:
        name = req.name.lower().replace('-', '_')
        if name not in pins:
            errors.append(f"  {req.name}: required by {req} but not found in requirements.txt")
            continue
        pinned = pins[name]
        if not req.specifier.contains(pinned, prereleases=True):
            errors.append(f"  {req.name}: pinned {pinned} does not satisfy {req.specifier}")

    if errors:
        print("requirements.txt does not satisfy input constraints:", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        print("\nRun 'make requirements' to regenerate.", file=sys.stderr)
        sys.exit(1)

    print("requirements.txt satisfies all constraints.")


if __name__ == '__main__':
    main()
