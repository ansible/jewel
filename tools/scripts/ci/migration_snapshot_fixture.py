#!/usr/bin/env python3
"""Seed and snapshot fixed synthetic rows for migration upgrade checks."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Sequence

import django
from django.apps import apps
from django.conf import settings
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

ORGANIZATION_NAME = "Migration CI Snapshot Organization"
TEAM_NAME = "Migration CI Snapshot Team"
LOCAL_DATABASE_HOSTS = frozenset({"", "localhost", "127.0.0.1", "::1"})
DATABASE_ROUTING_OPTIONS = frozenset({"conninfo", "database", "dbname", "dsn", "host", "hostaddr", "port", "service", "servicefile"})


class MigrationSnapshotFixtureError(RuntimeError):
    """Raised when the synthetic migration snapshot fixture is inconsistent."""


def validate_effective_database() -> None:
    """Require Django's resolved default database to match the local CI database."""
    try:
        django.setup()
        database = settings.DATABASES.get("default")
    except Exception as exc:
        raise MigrationSnapshotFixtureError("Unable to load migration snapshot database settings") from exc

    expected_name = os.environ.get("DATABASE_NAME")
    expected_port = os.environ.get("DATABASE_PORT") or "5432"
    if not isinstance(database, dict) or not isinstance(expected_name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", expected_name):
        raise MigrationSnapshotFixtureError("Snapshot round-trip requires a local PostgreSQL database")

    engine = database.get("ENGINE", "")
    name = database.get("NAME")
    host = database.get("HOST") or ""
    port = database.get("PORT") or "5432"
    options = database.get("OPTIONS", {})
    routing_options = {str(option).lower() for option in options} if isinstance(options, dict) else DATABASE_ROUTING_OPTIONS
    if (
        not isinstance(engine, str)
        or not engine.startswith("django.db.backends.postgresql")
        or name != expected_name
        or not isinstance(host, str)
        or host.lower() not in LOCAL_DATABASE_HOSTS
        or str(port) != expected_port
        or not isinstance(options, dict)
        or routing_options & DATABASE_ROUTING_OPTIONS
    ):
        raise MigrationSnapshotFixtureError("Snapshot round-trip requires a local PostgreSQL database")


def _models():
    try:
        validate_effective_database()
        organization_model = apps.get_model("aap_gateway_api", "Organization")
        team_model = apps.get_model("aap_gateway_api", "Team")
    except MigrationSnapshotFixtureError:
        raise
    except Exception as exc:
        raise MigrationSnapshotFixtureError("Unable to load migration snapshot fixture models") from exc
    if organization_model is None or team_model is None:
        raise MigrationSnapshotFixtureError("Migration snapshot fixture models are unavailable")
    return organization_model, team_model


def _matching_rows(model, name: str):
    return list(model.objects.filter(name=name).order_by("pk"))


def _snapshot(organization_model, team_model) -> dict[str, dict[str, str]]:
    organizations = _matching_rows(organization_model, ORGANIZATION_NAME)
    if len(organizations) != 1:
        raise MigrationSnapshotFixtureError("Snapshot requires exactly one organization")

    teams = _matching_rows(team_model, TEAM_NAME)
    if len(teams) != 1:
        raise MigrationSnapshotFixtureError("Snapshot requires exactly one team")

    organization = organizations[0]
    team = teams[0]
    if team.organization_id != organization.pk:
        raise MigrationSnapshotFixtureError("Snapshot team does not belong to the fixed organization")

    return {
        "organization": {
            "id": str(organization.pk),
            "name": organization.name,
        },
        "team": {
            "id": str(team.pk),
            "name": team.name,
            "organization_id": str(team.organization_id),
        },
    }


def seed_snapshot_fixture() -> dict[str, dict[str, str]]:
    """Create or repair the fixed synthetic organization and team."""
    organization_model, team_model = _models()
    try:
        organization_model.objects.get_or_create(name=ORGANIZATION_NAME, defaults={"managed": False})
        organizations = _matching_rows(organization_model, ORGANIZATION_NAME)
        if len(organizations) != 1:
            raise MigrationSnapshotFixtureError("Seed requires exactly one organization")
        organization = organizations[0]

        teams = _matching_rows(team_model, TEAM_NAME)
        if len(teams) > 1:
            raise MigrationSnapshotFixtureError("Seed requires at most one team")
        if teams:
            team = teams[0]
            if team.organization_id != organization.pk:
                team.organization = organization
                team.save(update_fields=["organization"])
        else:
            team_model.objects.get_or_create(name=TEAM_NAME, organization=organization)

        return _snapshot(organization_model, team_model)
    except MigrationSnapshotFixtureError:
        raise
    except Exception as exc:
        raise MigrationSnapshotFixtureError("Unable to seed migration snapshot fixtures") from exc


def snapshot_fixture() -> dict[str, dict[str, str]]:
    """Return exact identity for the fixed synthetic organization/team pair."""
    organization_model, team_model = _models()
    try:
        return _snapshot(organization_model, team_model)
    except MigrationSnapshotFixtureError:
        raise
    except Exception as exc:
        raise MigrationSnapshotFixtureError("Unable to inspect migration snapshot fixtures") from exc


def database_state_snapshot() -> dict[str, object]:
    """Capture aggregate table counts, applied migration keys, and fixed identities."""
    organization_model, team_model = _models()
    try:
        table_counts = {}
        with connection.cursor() as cursor:
            for table_name in sorted(connection.introspection.table_names()):
                cursor.execute(f"SELECT COUNT(*) FROM {connection.ops.quote_name(table_name)}")
                table_counts[table_name] = cursor.fetchone()[0]

        applied_migrations = sorted(f"{app_label}.{migration_name}" for app_label, migration_name in MigrationRecorder(connection).applied_migrations())
        return {
            "table_counts": table_counts,
            "applied_migrations": applied_migrations,
            "fixture": _snapshot(organization_model, team_model),
        }
    except MigrationSnapshotFixtureError:
        raise
    except Exception as exc:
        raise MigrationSnapshotFixtureError("Unable to capture migration database state") from exc


def write_snapshot(output_path: Path, snapshot: dict[str, object]) -> None:
    """Write sanitized identity JSON atomically."""
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
            json.dump(snapshot, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.replace(output_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("validate-connection", help="reject non-local effective database settings")
    actions.add_parser("seed", help="create the fixed synthetic organization and team")
    snapshot_parser = actions.add_parser("snapshot", help="write the fixed organization/team identity as JSON")
    snapshot_parser.add_argument("--output", required=True, type=Path, help="destination for sanitized identity JSON")
    state_parser = actions.add_parser("state", help="write aggregate database migration state and fixture identity as JSON")
    state_parser.add_argument("--output", required=True, type=Path, help="destination for sanitized state JSON")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.action == "validate-connection":
            validate_effective_database()
            print("Validated local PostgreSQL migration database configuration")
        elif args.action == "seed":
            seed_snapshot_fixture()
            print("Seeded fixed synthetic migration snapshot fixtures")
        elif args.action == "state":
            write_snapshot(args.output, database_state_snapshot())
            print("Wrote fixed synthetic migration state")
        else:
            write_snapshot(args.output, snapshot_fixture())
            print("Wrote fixed synthetic migration snapshot identity")
    except MigrationSnapshotFixtureError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
