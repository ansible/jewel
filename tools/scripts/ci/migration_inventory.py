#!/usr/bin/env python3
"""Collect and validate migration upgrade inventory data."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Sequence

POLICY_KEYS = frozenset(
    {
        "enforced_apps",
        "allowed_missing",
        "allowed_fingerprint_changes",
        "immutable_vcs_stages",
    }
)
INVENTORY_KEYS = frozenset({"stage", "checkout_sha", "available", "applied", "dependencies", "replacements", "vcs_dependencies"})
APP_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MIGRATION_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z0-9_]+$")
STAGE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
GIT_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
SAFE_COMMIT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{6,127}$")
SAFE_DISTRIBUTION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,127}$")
SAFE_PROVENANCE_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/+@-]{0,127}$")
SEMANTIC_TAG_PATTERN = re.compile(r"^v?(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


class MigrationInventoryError(ValueError):
    """Raised when migration inventory inputs are invalid."""


@dataclass(frozen=True)
class VcsProvenanceViolation:
    """One unsafe version-control dependency in an immutable stage."""

    distribution: str
    reason: str

    def message(self) -> str:
        return f"VCS dependency {self.distribution!r}: {self.reason}"


@dataclass(frozen=True)
class MigrationPolicy:
    """Rules for comparing migrations across ordered upgrade stages."""

    enforced_apps: frozenset[str]
    allowed_missing: frozenset[str]
    allowed_fingerprint_changes: frozenset[str]
    immutable_vcs_stages: frozenset[str]


def _read_json_object(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise MigrationInventoryError(f"Migration policy does not exist: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationInventoryError(f"Unable to read migration policy {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise MigrationInventoryError("Migration policy must be a JSON object")
    return payload


def _string_array(payload: dict[str, object], field: str) -> list[str]:
    value = payload[field]
    if not isinstance(value, list):
        raise MigrationInventoryError(f"Migration policy {field} must be an array")
    if not all(isinstance(item, str) for item in value):
        raise MigrationInventoryError(f"Migration policy {field} entries must be strings")
    if len(value) != len(set(value)):
        raise MigrationInventoryError(f"Migration policy contains duplicate entries in {field}")
    return value


def load_policy(path: Path) -> MigrationPolicy:
    """Load and strictly validate a migration-upgrade policy file."""
    payload = _read_json_object(path)
    keys = frozenset(payload)
    missing = POLICY_KEYS - keys
    unknown = keys - POLICY_KEYS
    if missing:
        raise MigrationInventoryError(f"Migration policy has missing keys: {', '.join(sorted(missing))}")
    if unknown:
        raise MigrationInventoryError(f"Migration policy has unknown keys: {', '.join(sorted(unknown))}")

    enforced_apps = _string_array(payload, "enforced_apps")
    allowed_missing = _string_array(payload, "allowed_missing")
    allowed_fingerprint_changes = _string_array(payload, "allowed_fingerprint_changes")
    immutable_vcs_stages = _string_array(payload, "immutable_vcs_stages")

    for app_label in enforced_apps:
        if not APP_PATTERN.fullmatch(app_label):
            raise MigrationInventoryError(f"Invalid enforced app label: {app_label!r}")

    enforced_app_set = frozenset(enforced_apps)
    for field, migration_keys in (
        ("allowed_missing", allowed_missing),
        ("allowed_fingerprint_changes", allowed_fingerprint_changes),
    ):
        for migration_key in migration_keys:
            if not MIGRATION_KEY_PATTERN.fullmatch(migration_key):
                raise MigrationInventoryError(f"Invalid migration key in {field}: {migration_key!r}")
            app_label = migration_key.split(".", 1)[0]
            if app_label not in enforced_app_set:
                raise MigrationInventoryError(f"Migration exception {migration_key!r} belongs to app {app_label!r}, which is not enforced")

    for stage in immutable_vcs_stages:
        if not STAGE_PATTERN.fullmatch(stage):
            raise MigrationInventoryError(f"Invalid immutable VCS stage name: {stage!r}")

    return MigrationPolicy(
        enforced_apps=enforced_app_set,
        allowed_missing=frozenset(allowed_missing),
        allowed_fingerprint_changes=frozenset(allowed_fingerprint_changes),
        immutable_vcs_stages=frozenset(immutable_vcs_stages),
    )


def _migration_key(key: tuple[str, str]) -> str:
    return f"{key[0]}.{key[1]}"


def _migration_source_path(migration_key: str, migration: object) -> Path:
    module_name = migration.__class__.__module__
    module = importlib.import_module(module_name)
    source_text = getattr(module, "__file__", None)
    if not source_text:
        raise MigrationInventoryError(f"Migration {migration_key} has no source file")

    source_path = Path(source_text)
    if source_path.suffix == ".pyc":
        source_path = source_path.with_suffix(".py")
    if source_path.suffix != ".py":
        raise MigrationInventoryError(f"Migration {migration_key} source file is not Python source: {source_path}")
    if not source_path.is_file():
        raise MigrationInventoryError(f"Migration {migration_key} source file does not exist: {source_path}")
    return source_path


def _vcs_dependencies() -> list[dict[str, object]]:
    dependencies: list[dict[str, object]] = []
    for distribution in metadata.distributions():
        direct_url_text = distribution.read_text("direct_url.json")
        if not direct_url_text:
            continue
        distribution_name = distribution.metadata.get("Name") or "unknown"
        if not isinstance(distribution_name, str) or not SAFE_DISTRIBUTION_PATTERN.fullmatch(distribution_name):
            raise MigrationInventoryError("VCS metadata has an unsafe distribution name")
        try:
            direct_url = json.loads(direct_url_text)
        except json.JSONDecodeError as exc:
            raise MigrationInventoryError(f"Invalid direct_url.json for {distribution_name}: {exc}") from exc
        if not isinstance(direct_url, dict):
            raise MigrationInventoryError(f"Invalid direct_url.json for {distribution_name}: expected an object")

        vcs_info = direct_url.get("vcs_info")
        if vcs_info is None:
            continue
        if not isinstance(vcs_info, dict):
            raise MigrationInventoryError(f"Invalid VCS metadata for {distribution_name}")
        commit_id = vcs_info.get("commit_id")
        vcs = vcs_info.get("vcs")
        if not isinstance(vcs, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", vcs):
            raise MigrationInventoryError(f"VCS metadata for {distribution_name} has no safe VCS type")
        commit_pattern = GIT_SHA_PATTERN if vcs == "git" else SAFE_COMMIT_PATTERN
        if not isinstance(commit_id, str) or not commit_pattern.fullmatch(commit_id):
            raise MigrationInventoryError(f"VCS metadata for {distribution_name} has no commit_id")
        requested_revision = vcs_info.get("requested_revision")
        if requested_revision is not None and (not isinstance(requested_revision, str) or not SAFE_PROVENANCE_REF_PATTERN.fullmatch(requested_revision)):
            raise MigrationInventoryError(f"VCS metadata for {distribution_name} has an unsafe requested_revision")
        dir_info = direct_url.get("dir_info", {})
        if not isinstance(dir_info, dict):
            raise MigrationInventoryError(f"VCS metadata for {distribution_name} has invalid dir_info")
        editable = dir_info.get("editable", False)
        if not isinstance(editable, bool):
            raise MigrationInventoryError(f"VCS metadata for {distribution_name} has an invalid editable flag")

        dependencies.append(
            {
                "distribution": distribution_name,
                "vcs": vcs,
                "requested_revision": requested_revision,
                "commit_id": commit_id,
                "editable": editable,
            }
        )
    return sorted(dependencies, key=lambda item: (str(item["distribution"]).lower(), str(item["commit_id"])))


def build_inventory(stage: str, checkout_sha: str) -> dict[str, object]:
    """Collect migration graph, applied history, and safe VCS provenance."""
    if not STAGE_PATTERN.fullmatch(stage):
        raise MigrationInventoryError(f"Invalid stage name: {stage!r}")
    if not re.fullmatch(r"[0-9a-fA-F]{7,64}", checkout_sha):
        raise MigrationInventoryError(f"Invalid checkout SHA: {checkout_sha!r}")

    # Django only exists in the stage venv; keep imports local so the host runner
    # can start with the stdlib interpreter from actions/setup-python.
    import django
    from django.db import connection
    from django.db.migrations.loader import MigrationLoader
    from django.db.migrations.recorder import MigrationRecorder

    django.setup()
    loader = MigrationLoader(connection)
    recorder = MigrationRecorder(connection)

    available: dict[str, str] = {}
    dependencies: dict[str, list[str]] = {}
    replacements: dict[str, list[str]] = {}
    for key in sorted(loader.disk_migrations):
        migration = loader.disk_migrations[key]
        migration_key = _migration_key(key)
        source_path = _migration_source_path(migration_key, migration)
        available[migration_key] = hashlib.sha256(source_path.read_bytes()).hexdigest()
        dependencies[migration_key] = sorted(_migration_key(item) for item in migration.dependencies)
        replacements[migration_key] = sorted(_migration_key(item) for item in migration.replaces)

    applied = sorted(_migration_key(key) for key in recorder.applied_migrations())
    return {
        "stage": stage,
        "checkout_sha": checkout_sha,
        "available": available,
        "applied": applied,
        "dependencies": dependencies,
        "replacements": replacements,
        "vcs_dependencies": _vcs_dependencies(),
    }


def write_inventory(output_path: Path, inventory: dict[str, object]) -> None:
    """Atomically write an inventory JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(inventory, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.replace(output_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def validate_inventory(inventory: object, *, expected_stage: str, expected_checkout_sha: str) -> dict[str, object]:
    """Validate the collector schema and bind it to the requested stage."""
    if not isinstance(inventory, dict):
        raise MigrationInventoryError("inventory must be an object")

    keys = frozenset(inventory)
    missing = INVENTORY_KEYS - keys
    unknown = keys - INVENTORY_KEYS
    if missing:
        raise MigrationInventoryError(f"inventory is missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise MigrationInventoryError(f"inventory has unknown fields: {', '.join(sorted(unknown))}")

    if inventory["stage"] != expected_stage:
        raise MigrationInventoryError(f"inventory stage does not match requested stage {expected_stage!r}")
    if inventory["checkout_sha"] != expected_checkout_sha:
        raise MigrationInventoryError("inventory checkout SHA does not match requested checkout")

    available = inventory["available"]
    if not isinstance(available, dict):
        raise MigrationInventoryError("inventory available must be an object")
    for migration_key, fingerprint in available.items():
        if not isinstance(migration_key, str) or not MIGRATION_KEY_PATTERN.fullmatch(migration_key):
            raise MigrationInventoryError(f"inventory has invalid migration key: {migration_key!r}")
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise MigrationInventoryError(f"inventory has invalid fingerprint for {migration_key}")

    applied = inventory["applied"]
    if not isinstance(applied, list) or not all(isinstance(item, str) for item in applied):
        raise MigrationInventoryError("inventory applied must be an array of migration keys")
    if len(applied) != len(set(applied)):
        raise MigrationInventoryError("inventory applied contains duplicate migration keys")
    if any(not MIGRATION_KEY_PATTERN.fullmatch(item) for item in applied):
        raise MigrationInventoryError("inventory applied contains an invalid migration key")

    for field_name in ("dependencies", "replacements"):
        graph = inventory[field_name]
        if not isinstance(graph, dict) or set(graph) != set(available):
            raise MigrationInventoryError(f"inventory {field_name} keys must match available migrations")
        for migration_key, related in graph.items():
            if not isinstance(related, list) or not all(isinstance(item, str) and MIGRATION_KEY_PATTERN.fullmatch(item) for item in related):
                raise MigrationInventoryError(f"inventory {field_name} for {migration_key} must be an array of migration keys")

    vcs_dependencies = inventory["vcs_dependencies"]
    if not isinstance(vcs_dependencies, list):
        raise MigrationInventoryError("inventory vcs_dependencies must be an array")
    for dependency in vcs_dependencies:
        if not isinstance(dependency, dict):
            raise MigrationInventoryError("inventory VCS dependency must be an object")
        if set(dependency) != {"distribution", "vcs", "requested_revision", "commit_id", "editable"}:
            raise MigrationInventoryError("inventory VCS dependency has invalid fields")
        if not isinstance(dependency["distribution"], str) or not SAFE_DISTRIBUTION_PATTERN.fullmatch(dependency["distribution"]):
            raise MigrationInventoryError("inventory VCS dependency has invalid distribution name")
        if not isinstance(dependency["vcs"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", dependency["vcs"]):
            raise MigrationInventoryError("inventory VCS dependency has invalid VCS type")
        commit_pattern = GIT_SHA_PATTERN if dependency["vcs"] == "git" else SAFE_COMMIT_PATTERN
        if not isinstance(dependency["commit_id"], str) or not commit_pattern.fullmatch(dependency["commit_id"]):
            raise MigrationInventoryError("inventory VCS dependency has invalid identity fields")
        requested_revision = dependency["requested_revision"]
        if requested_revision is not None and (not isinstance(requested_revision, str) or not SAFE_PROVENANCE_REF_PATTERN.fullmatch(requested_revision)):
            raise MigrationInventoryError("inventory VCS dependency has invalid requested_revision")
        if not isinstance(dependency["editable"], bool):
            raise MigrationInventoryError("inventory VCS dependency has invalid editable flag")

    return inventory


def validate_vcs_provenance(inventory: dict[str, object], policy: MigrationPolicy) -> list[VcsProvenanceViolation]:
    """Reject mutable VCS inputs for policy-selected stages.

    Only a full Git commit is immutable. Tags are recorded with their resolved
    commit, but the tag itself may still be moved between runs.
    """
    stage = inventory.get("stage")
    if not isinstance(stage, str):
        raise MigrationInventoryError("inventory stage must be a string")
    if stage not in policy.immutable_vcs_stages:
        return []

    dependencies = inventory.get("vcs_dependencies")
    if not isinstance(dependencies, list):
        raise MigrationInventoryError("inventory vcs_dependencies must be an array")

    violations: list[VcsProvenanceViolation] = []
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            raise MigrationInventoryError("inventory VCS dependency must be an object")
        distribution = dependency.get("distribution")
        safe_distribution = distribution if isinstance(distribution, str) else "unknown"
        requested_revision = dependency.get("requested_revision")
        commit_id = dependency.get("commit_id")

        if dependency.get("editable") is True:
            reason = "editable installs are not permitted"
        elif dependency.get("vcs") != "git":
            reason = "only Git dependencies are supported for immutable-stage validation"
        elif not isinstance(commit_id, str) or not GIT_SHA_PATTERN.fullmatch(commit_id):
            reason = "resolved commit is missing or is not a full Git SHA"
        elif not isinstance(requested_revision, str) or not requested_revision:
            reason = "requested revision is missing"
        elif GIT_SHA_PATTERN.fullmatch(requested_revision):
            if requested_revision.lower() != commit_id.lower():
                reason = "requested commit does not match the resolved commit"
            else:
                continue
        else:
            reason = "requested revision must be a full Git SHA"

        violations.append(VcsProvenanceViolation(distribution=safe_distribution, reason=reason))

    return sorted(violations, key=lambda violation: (violation.distribution.lower(), violation.reason))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--checkout-sha", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    inventory = build_inventory(args.stage, args.checkout_sha)
    write_inventory(args.output, inventory)
    print(
        f"Wrote migration inventory {args.output} "
        f"(available={len(inventory['available'])}, applied={len(inventory['applied'])}, "
        f"vcs={len(inventory['vcs_dependencies'])})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
