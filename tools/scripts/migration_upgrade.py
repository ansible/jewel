#!/usr/bin/env python3
"""Run Django migrations through a sequence of gateway checkouts.

Each checkout gets its own virtual environment, while every migration command
uses the same database configured through the process environment.  This
exercises the upgrade path that a release branch will use in production.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence

from ci.migration_inventory import MigrationInventoryError, MigrationPolicy, load_policy, validate_inventory, validate_vcs_provenance

NOOP_MIGRATION_MESSAGE = "No migrations to apply."
SNAPSHOT_DATABASE_PATTERN = re.compile(r"^gw_migration_snapshot_[0-9a-f]{16}$")
DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,62}$")
LOCAL_DATABASE_HOSTS = frozenset({"", "localhost", "127.0.0.1", "::1"})
MIGRATION_SNAPSHOT = """\
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute(\"SELECT app, name FROM django_migrations ORDER BY app, name\")
    for app, name in cursor.fetchall():
        print(f\"{app}.{name}\")
"""


class MigrationUpgradeError(RuntimeError):
    """Raised when an upgrade stage cannot be completed safely."""


@dataclass(frozen=True)
class Stage:
    name: str
    path: Path


@dataclass
class StageResult:
    name: str
    path: Path
    sha: str
    log_path: Path
    status: str = "pending"
    error: str | None = None
    inventory_path: Path | None = None
    inventory: dict[str, object] | None = None
    policy_exceptions: list[str] = field(default_factory=list)
    snapshot_diagnostic_path: Path | None = None
    snapshot_result: dict[str, object] | None = None
    fixture_snapshot_path: Path | None = None


@dataclass(frozen=True)
class InventoryViolation:
    """One migration inventory policy violation."""

    kind: str
    stage: str
    migration: str
    first_stage: str
    first_fingerprint: str | None
    current_fingerprint: str | None

    def message(self) -> str:
        if self.kind == "missing":
            return f"stage {self.stage} is missing applied migration {self.migration} first observed in {self.first_stage}"
        return (
            f"stage {self.stage} changed applied migration {self.migration} first observed in {self.first_stage}: "
            f"{self.first_fingerprint} -> {self.current_fingerprint}"
        )


CommandResult = subprocess.CompletedProcess[str]
RunCommand = Callable[..., CommandResult]
GitSha = Callable[[Path], str]
SnapshotDatabaseNameFactory = Callable[[], str]


def new_snapshot_database_name() -> str:
    """Return a low-collision, non-sensitive temporary PostgreSQL name."""
    return f"gw_migration_snapshot_{secrets.token_hex(8)}"


def _inventory_events(
    inventories: Sequence[dict[str, object]],
    policy: MigrationPolicy,
) -> tuple[list[InventoryViolation], list[str]]:
    first_applied: dict[str, tuple[str, str | None]] = {}
    violations: list[InventoryViolation] = []
    exceptions: list[str] = []

    for inventory in inventories:
        stage = str(inventory["stage"])
        available = dict(inventory["available"])
        applied = sorted(str(item) for item in inventory["applied"])
        for migration in applied:
            app_label = migration.split(".", 1)[0]
            if app_label in policy.enforced_apps:
                first_applied.setdefault(migration, (stage, available.get(migration)))

        for migration, (first_stage, first_fingerprint) in sorted(first_applied.items()):
            current_fingerprint = available.get(migration)
            if current_fingerprint is None:
                if migration in policy.allowed_missing:
                    exceptions.append(f"{stage}: allowed missing migration {migration}")
                else:
                    violations.append(
                        InventoryViolation(
                            kind="missing",
                            stage=stage,
                            migration=migration,
                            first_stage=first_stage,
                            first_fingerprint=first_fingerprint,
                            current_fingerprint=None,
                        )
                    )
            elif first_fingerprint is not None and current_fingerprint != first_fingerprint:
                if migration in policy.allowed_fingerprint_changes:
                    exceptions.append(f"{stage}: allowed fingerprint change for migration {migration}")
                else:
                    violations.append(
                        InventoryViolation(
                            kind="fingerprint",
                            stage=stage,
                            migration=migration,
                            first_stage=first_stage,
                            first_fingerprint=first_fingerprint,
                            current_fingerprint=str(current_fingerprint),
                        )
                    )

    return violations, sorted(set(exceptions))


def compare_inventory_history(inventories: Sequence[dict[str, object]], policy: MigrationPolicy) -> list[InventoryViolation]:
    """Return deterministic migration inventory policy violations."""
    return _inventory_events(inventories, policy)[0]


def find_policy_exceptions(inventories: Sequence[dict[str, object]], policy: MigrationPolicy) -> list[str]:
    """Return deterministic policy exceptions exercised by the inventories."""
    return _inventory_events(inventories, policy)[1]


def parse_stage_spec(spec: str) -> Stage:
    """Parse a ``name=checkout-path`` command-line value."""
    if spec.count("=") != 1:
        raise ValueError(f"Invalid stage specification: {spec!r}; expected name=path")

    name, path_text = spec.split("=", 1)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise ValueError(f"Invalid stage name: {name!r}")
    if not path_text:
        raise ValueError(f"Stage {name!r} has no checkout path")

    return Stage(name=name, path=Path(path_text).expanduser().resolve())


def run_command(command: Sequence[str], *, cwd: Path, env: Mapping[str, str]) -> CommandResult:
    """Run one command and capture its output for the stage log."""
    return subprocess.run(
        list(command),
        cwd=cwd,
        env=dict(env),
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )


def git_sha(path: Path) -> str:
    """Return the checked-out commit SHA for a stage."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout.strip()


class MigrationUpgradeRunner:
    """Install and validate each checkout in order against one database."""

    def __init__(
        self,
        *,
        stages: Sequence[Stage],
        output_dir: Path,
        venv_root: Path,
        run_command: RunCommand = run_command,
        git_sha: GitSha = git_sha,
        base_env: Mapping[str, str] | None = None,
        python_executable: str = sys.executable,
        policy_path: Path,
        snapshot_round_trip_after: str | None = None,
        snapshot_database_name_factory: SnapshotDatabaseNameFactory = new_snapshot_database_name,
    ) -> None:
        self.stages = list(stages)
        self.output_dir = output_dir
        self.venv_root = venv_root
        self.run_command = run_command
        self.git_sha = git_sha
        self.base_env = dict(os.environ if base_env is None else base_env)
        self.python_executable = python_executable
        self.policy_path = policy_path
        self.snapshot_round_trip_after = snapshot_round_trip_after
        self.snapshot_database_name_factory = snapshot_database_name_factory
        self.results: list[StageResult] = []
        self.inventories: list[dict[str, object]] = []
        self.policy: MigrationPolicy | None = None
        self.inventory_helper_path = self.venv_root / "_helpers" / "migration_inventory.py"
        self.snapshot_fixture_helper_path = self.venv_root / "_helpers" / "migration_snapshot_fixture.py"
        self.snapshot_database_name: str | None = None
        self.snapshot_stage: Stage | None = None
        self.expected_fixture_snapshot: dict[str, object] | None = None
        self.snapshot_cleanup_warning: str | None = None

    def run(self) -> None:
        if not self.stages:
            raise MigrationUpgradeError("At least one migration upgrade stage is required")

        duplicate_names = sorted(name for name, count in Counter(stage.name for stage in self.stages).items() if count > 1)
        if duplicate_names:
            names = ", ".join(repr(name) for name in duplicate_names)
            raise MigrationUpgradeError(f"Duplicate migration stage names: {names}")

        if self.snapshot_round_trip_after is not None:
            stage_names = [stage.name for stage in self.stages]
            if self.snapshot_round_trip_after not in stage_names:
                raise MigrationUpgradeError(f"Unknown migration stage for snapshot round-trip: {self.snapshot_round_trip_after!r}")
            if stage_names[-1] == self.snapshot_round_trip_after:
                raise MigrationUpgradeError("Snapshot round-trip stage must leave at least one later stage")
            self._validate_snapshot_environment(self.base_env)

        try:
            self.policy = load_policy(self.policy_path)
        except MigrationInventoryError as exc:
            raise MigrationUpgradeError(f"Invalid migration inventory policy: {exc}") from exc

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.venv_root.mkdir(parents=True, exist_ok=True)
        self.inventory_helper_path.parent.mkdir(parents=True, exist_ok=True)
        helper_sources = (
            (Path(__file__).parent / "ci" / "migration_inventory.py", self.inventory_helper_path),
            (Path(__file__).parent / "ci" / "migration_snapshot_fixture.py", self.snapshot_fixture_helper_path),
        )
        try:
            for helper_source, helper_destination in helper_sources:
                shutil.copy2(helper_source, helper_destination)
        except OSError as exc:
            raise MigrationUpgradeError("Unable to prepare migration validation helpers") from exc

        for stage in self.stages:
            try:
                stage_sha = self._stage_sha(stage)
            except MigrationUpgradeError as exc:
                self.results.append(
                    StageResult(
                        name=stage.name,
                        path=stage.path,
                        sha="unavailable",
                        log_path=self.output_dir / f"{stage.name}.log",
                        status="failed",
                        error=str(exc),
                    )
                )
                self._cleanup_snapshot_database()
                self._write_summary_best_effort()
                raise
            result = StageResult(
                name=stage.name,
                path=stage.path,
                sha=stage_sha,
                log_path=self.output_dir / f"{stage.name}.log",
            )
            self.results.append(result)

            try:
                self._run_stage(stage, result)
            except MigrationUpgradeError as exc:
                result.status = "failed"
                result.error = str(exc)
                self._cleanup_snapshot_database()
                self._write_summary_best_effort()
                raise
            else:
                result.status = "passed"
                try:
                    self._write_summary()
                except Exception as exc:
                    result.status = "failed"
                    result.error = f"Summary write failed: {exc}"
                    self._cleanup_snapshot_database()
                    self._write_summary_best_effort()
                    raise MigrationUpgradeError(result.error) from exc

        self._cleanup_snapshot_database()
        try:
            self._write_summary()
        except Exception as exc:
            raise MigrationUpgradeError(f"Summary write failed: {exc}") from exc

    def _stage_sha(self, stage: Stage) -> str:
        if not stage.path.is_dir():
            raise MigrationUpgradeError(f"Stage {stage.name!r} checkout does not exist: {stage.path}")
        try:
            return self.git_sha(stage.path)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise MigrationUpgradeError(f"Stage {stage.name!r} is not a git checkout: {stage.path}") from exc

    @staticmethod
    def _validate_snapshot_environment(env: Mapping[str, str]) -> str:
        database_name = env.get("DATABASE_NAME")
        if not isinstance(database_name, str) or not DATABASE_NAME_PATTERN.fullmatch(database_name):
            raise MigrationUpgradeError("Snapshot round-trip requires a simple DATABASE_NAME identifier")
        database_engine = env.get("DATABASE_ENGINE", "")
        if not database_engine.startswith("django.db.backends.postgresql"):
            raise MigrationUpgradeError("Snapshot round-trip requires a PostgreSQL database engine")
        database_host = env.get("DATABASE_HOST", env.get("PGHOST", ""))
        if database_host not in LOCAL_DATABASE_HOSTS:
            raise MigrationUpgradeError("Snapshot round-trip is restricted to a local PostgreSQL database")
        return database_name

    def _stage_env(self, stage: Stage, venv_dir: Path) -> dict[str, str]:
        # Keep ambient libpq routing variables from overriding Django's explicit
        # DATABASE_* configuration for any stage or fixture-helper process.
        env = {key: value for key, value in self.base_env.items() if not key.startswith("PG")}
        for source, destination in (
            ("DATABASE_USER", "PGUSER"),
            ("DATABASE_PASSWORD", "PGPASSWORD"),
            ("DATABASE_HOST", "PGHOST"),
            ("DATABASE_PORT", "PGPORT"),
            ("DATABASE_NAME", "PGDATABASE"),
        ):
            if source in env:
                env[destination] = env[source]
        venv_bin = venv_dir / "bin"
        env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(stage.path), env.get("PYTHONPATH", "")]))
        env.setdefault("DJANGO_SETTINGS_MODULE", "aap_gateway_api.settings")
        return env

    def _run_stage(self, stage: Stage, result: StageResult) -> None:
        venv_dir = self.venv_root / stage.name
        env = self._stage_env(stage, venv_dir)

        with result.log_path.open("w", encoding="utf-8") as log:
            self._execute(
                [self.python_executable, "-m", "venv", str(venv_dir)],
                stage=stage,
                result=result,
                env=env,
                log=log,
            )

            install_script = stage.path / "tools/scripts/ci/install_django_venv.sh"
            self._execute(
                [str(install_script), str(venv_dir)],
                stage=stage,
                result=result,
                env=env,
                log=log,
            )

            if self.snapshot_round_trip_after is not None:
                self._execute(
                    [str(venv_dir / "bin" / "python"), str(self.snapshot_fixture_helper_path), "validate-connection"],
                    stage=stage,
                    result=result,
                    env=env,
                    log=log,
                )

            manage = [str(venv_dir / "bin" / "python"), "-m", "aap_gateway_api"]
            self._execute(manage + ["migrate", "--noinput"], stage=stage, result=result, env=env, log=log)
            self._execute(manage + ["migrate", "--check"], stage=stage, result=result, env=env, log=log)
            self._execute(manage + ["showmigrations", "--plan"], stage=stage, result=result, env=env, log=log)
            self._execute(manage + ["shell", "-c", MIGRATION_SNAPSHOT], stage=stage, result=result, env=env, log=log)
            second_migrate = self._execute(
                manage + ["migrate", "--noinput"],
                stage=stage,
                result=result,
                env=env,
                log=log,
            )

            output = f"{second_migrate.stdout or ''}\n{second_migrate.stderr or ''}"
            if NOOP_MIGRATION_MESSAGE not in output:
                raise MigrationUpgradeError(f"Stage {stage.name!r} second migrate was not a no-op; expected {NOOP_MIGRATION_MESSAGE!r}")

            inventory_path = self.output_dir / f"{stage.name}.inventory.json"
            result.inventory_path = inventory_path
            inventory_path.unlink(missing_ok=True)
            self._execute(
                [
                    str(venv_dir / "bin" / "python"),
                    str(self.inventory_helper_path),
                    "--stage",
                    stage.name,
                    "--checkout-sha",
                    result.sha,
                    "--output",
                    str(inventory_path),
                ],
                stage=stage,
                result=result,
                env=env,
                log=log,
            )
            if not inventory_path.is_file():
                raise MigrationUpgradeError(f"Stage {stage.name!r} inventory collector did not produce inventory: {inventory_path}")
            try:
                inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise MigrationUpgradeError(f"Stage {stage.name!r} produced invalid inventory JSON: {exc}") from exc
            try:
                inventory = validate_inventory(inventory, expected_stage=stage.name, expected_checkout_sha=result.sha)
            except MigrationInventoryError as exc:
                raise MigrationUpgradeError(f"Stage {stage.name!r} produced invalid inventory JSON: {exc}") from exc
            result.inventory = inventory
            self.inventories.append(inventory)
            assert self.policy is not None
            provenance_violations = validate_vcs_provenance(inventory, self.policy)
            if provenance_violations:
                details = "; ".join(item.message() for item in provenance_violations)
                raise MigrationUpgradeError(f"Stage {stage.name!r} has unsafe VCS dependency provenance: {details}")
            result.policy_exceptions = [item for item in find_policy_exceptions(self.inventories, self.policy) if item.startswith(f"{stage.name}:")]
            current_violations = [item for item in compare_inventory_history(self.inventories, self.policy) if item.stage == stage.name]
            if current_violations:
                details = "; ".join(item.message() for item in current_violations)
                raise MigrationUpgradeError(f"Migration inventory policy violation: {details}")

            if stage.name == self.snapshot_round_trip_after:
                self._run_snapshot_round_trip(stage, result, env, log)
            elif self.expected_fixture_snapshot is not None:
                self._verify_fixture_after_stage(stage, result, env, log)

    def _run_snapshot_round_trip(self, stage: Stage, result: StageResult, env: Mapping[str, str], log) -> None:
        diagnostic_path = self.output_dir / "snapshot-round-trip.json"
        result.snapshot_diagnostic_path = diagnostic_path
        result.snapshot_result = {"status": "running"}
        try:
            database_name = self.snapshot_database_name_factory()
        except Exception as exc:
            result.snapshot_result["status"] = "failed"
            raise MigrationUpgradeError("Unable to generate a snapshot database name") from exc
        if not isinstance(database_name, str) or not SNAPSHOT_DATABASE_PATTERN.fullmatch(database_name):
            result.snapshot_result["status"] = "failed"
            raise MigrationUpgradeError("Generated snapshot database name is invalid")

        try:
            original_database = self._validate_snapshot_environment(env)
        except MigrationUpgradeError:
            result.snapshot_result["status"] = "failed"
            raise

        self.snapshot_database_name = database_name
        self.snapshot_stage = stage
        dump_path = self.venv_root / f"{database_name}.dump"
        source_state_path = self.output_dir / "snapshot-source.json"
        restored_state_path = self.output_dir / "snapshot-restored.json"
        stage_python = str(self.venv_root / stage.name / "bin" / "python")
        fixture_command = [stage_python, str(self.snapshot_fixture_helper_path)]
        pg_env = self._postgres_env(env)
        round_trip_error: MigrationUpgradeError | None = None
        expected_fixture_snapshot: dict[str, object] | None = None

        try:
            for stale_path in (dump_path, source_state_path, restored_state_path, diagnostic_path):
                stale_path.unlink(missing_ok=True)
            self._run_snapshot_command(fixture_command + ["seed"], "seed synthetic fixture", stage, env, log)
            self._run_snapshot_command(
                fixture_command + ["state", "--output", str(source_state_path)],
                "capture source state",
                stage,
                env,
                log,
            )
            source_state = self._read_state_snapshot(source_state_path)

            self._run_snapshot_command(
                [
                    "pg_dump",
                    "--format=custom",
                    "--no-owner",
                    "--no-privileges",
                    "--file",
                    str(dump_path),
                    "--dbname",
                    original_database,
                ],
                "pg_dump",
                stage,
                pg_env,
                log,
            )
            if not dump_path.is_file():
                raise MigrationUpgradeError("Snapshot pg_dump did not create a dump")
            dump_sha256 = self._sha256_file(dump_path)

            self._run_snapshot_command(
                ["createdb", "--maintenance-db=postgres", "--template=template0", database_name],
                "createdb",
                stage,
                pg_env,
                log,
            )
            self._run_snapshot_command(
                [
                    "pg_restore",
                    "--exit-on-error",
                    "--no-owner",
                    "--no-privileges",
                    "--dbname",
                    database_name,
                    str(dump_path),
                ],
                "pg_restore",
                stage,
                pg_env,
                log,
            )

            restored_env = dict(env)
            restored_env["DATABASE_NAME"] = database_name
            restored_env["PGDATABASE"] = database_name
            self._run_snapshot_command(
                fixture_command + ["state", "--output", str(restored_state_path)],
                "capture restored state",
                stage,
                restored_env,
                log,
            )
            restored_state = self._read_state_snapshot(restored_state_path)
            status = "passed" if source_state == restored_state else "failed"
            diagnostic = {
                "stage": stage.name,
                "status": status,
                "dump_sha256": dump_sha256,
                "source": source_state,
                "restored": restored_state,
            }
            self._write_json_atomically(diagnostic_path, diagnostic)
            result.snapshot_result = diagnostic
            if status != "passed":
                raise MigrationUpgradeError("Snapshot restore changed table counts, applied migrations, or fixture identity")

            expected_fixture_snapshot = source_state["fixture"]
        except MigrationUpgradeError as exc:
            if result.snapshot_result is not None:
                result.snapshot_result["status"] = "failed"
            round_trip_error = exc
        except (OSError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
            if result.snapshot_result is not None:
                result.snapshot_result["status"] = "failed"
            round_trip_error = MigrationUpgradeError("Snapshot round-trip failed while handling sanitized diagnostics")
            round_trip_error.__cause__ = exc
        finally:
            try:
                dump_path.unlink(missing_ok=True)
            except OSError:
                self.snapshot_cleanup_warning = "Unable to remove the temporary snapshot dump"
                if round_trip_error is None:
                    round_trip_error = MigrationUpgradeError("Unable to remove the temporary snapshot dump")

        if round_trip_error is not None:
            if result.snapshot_result is not None and result.snapshot_result.get("status") != "failed":
                result.snapshot_result["status"] = "failed"
                try:
                    self._write_json_atomically(diagnostic_path, result.snapshot_result)
                except OSError:
                    pass
            raise round_trip_error

        assert expected_fixture_snapshot is not None
        self.expected_fixture_snapshot = expected_fixture_snapshot
        self.base_env["DATABASE_NAME"] = database_name

    def _run_snapshot_command(self, command: Sequence[str], description: str, stage: Stage, env: Mapping[str, str], log) -> None:
        log.write(f"[snapshot] {description}\n")
        log.flush()
        try:
            completed = self.run_command(command, cwd=stage.path, env=env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MigrationUpgradeError(f"Snapshot {description} could not be completed") from exc
        if completed.returncode:
            raise MigrationUpgradeError(f"Snapshot {description} failed with exit code {completed.returncode}")

    def _postgres_env(self, env: Mapping[str, str]) -> dict[str, str]:
        # Do not allow ambient libpq routing or service-file variables to
        # override the explicitly validated local connection settings.
        postgres_env = {key: value for key, value in env.items() if not key.startswith("PG")}
        for source, destination in (
            ("DATABASE_USER", "PGUSER"),
            ("DATABASE_PASSWORD", "PGPASSWORD"),
            ("DATABASE_HOST", "PGHOST"),
            ("DATABASE_PORT", "PGPORT"),
        ):
            if source in env:
                postgres_env[destination] = env[source]
        postgres_env["PGDATABASE"] = "postgres"
        return postgres_env

    def _read_state_snapshot(self, path: Path) -> dict[str, object]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MigrationUpgradeError("Snapshot helper did not write valid state JSON") from exc
        if not isinstance(payload, dict) or set(payload) != {"table_counts", "applied_migrations", "fixture"}:
            raise MigrationUpgradeError("Snapshot helper wrote an invalid state shape")

        table_counts = payload["table_counts"]
        if not isinstance(table_counts, dict) or any(
            not isinstance(table, str) or not re.fullmatch(r"[A-Za-z0-9_]+", table) or not isinstance(count, int) or isinstance(count, bool) or count < 0
            for table, count in table_counts.items()
        ):
            raise MigrationUpgradeError("Snapshot helper wrote invalid table counts")

        applied_migrations = payload["applied_migrations"]
        if not isinstance(applied_migrations, list) or any(
            not isinstance(migration, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z0-9_]+", migration) for migration in applied_migrations
        ):
            raise MigrationUpgradeError("Snapshot helper wrote invalid applied migration keys")

        fixture = payload["fixture"]
        if not isinstance(fixture, dict) or set(fixture) != {"organization", "team"}:
            raise MigrationUpgradeError("Snapshot helper wrote an invalid fixture identity")
        organization = fixture["organization"]
        team = fixture["team"]
        if (
            not isinstance(organization, dict)
            or set(organization) != {"id", "name"}
            or not isinstance(organization.get("id"), str)
            or not re.fullmatch(r"[A-Za-z0-9-]+", organization["id"])
            or organization.get("name") != "Migration CI Snapshot Organization"
            or not isinstance(team, dict)
            or set(team) != {"id", "name", "organization_id"}
            or not isinstance(team.get("id"), str)
            or not re.fullmatch(r"[A-Za-z0-9-]+", team["id"])
            or team.get("name") != "Migration CI Snapshot Team"
            or team.get("organization_id") != organization["id"]
        ):
            raise MigrationUpgradeError("Snapshot helper wrote an invalid fixture identity")

        return payload

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as dump:
            for block in iter(lambda: dump.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _write_json_atomically(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(payload, temporary, indent=2, sort_keys=True)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.replace(path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _verify_fixture_after_stage(self, stage: Stage, result: StageResult, env: Mapping[str, str], log) -> None:
        fixture_path = self.output_dir / f"{stage.name}.snapshot.json"
        result.fixture_snapshot_path = fixture_path
        fixture_path.unlink(missing_ok=True)
        command = [
            str(self.venv_root / stage.name / "bin" / "python"),
            str(self.snapshot_fixture_helper_path),
            "snapshot",
            "--output",
            str(fixture_path),
        ]
        self._run_snapshot_command(command, "verify fixed fixture identity", stage, env, log)
        try:
            fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MigrationUpgradeError(f"Stage {stage.name!r} snapshot helper did not write valid fixture JSON") from exc
        if fixture != self.expected_fixture_snapshot:
            raise MigrationUpgradeError(f"Stage {stage.name!r} changed the fixed snapshot fixture identity")

    def _cleanup_snapshot_database(self) -> None:
        if self.snapshot_database_name is None or self.snapshot_stage is None:
            return
        database_name = self.snapshot_database_name
        stage = self.snapshot_stage
        self.snapshot_database_name = None
        env = self._postgres_env(self._stage_env(stage, self.venv_root / stage.name))
        try:
            result = self.run_command(
                ["dropdb", "--if-exists", "--maintenance-db=postgres", database_name],
                cwd=stage.path,
                env=env,
            )
            if result.returncode:
                self.snapshot_cleanup_warning = "Unable to remove the temporary snapshot database"
        except Exception:
            self.snapshot_cleanup_warning = "Unable to remove the temporary snapshot database"

    def _execute(
        self,
        command: Sequence[str],
        *,
        stage: Stage,
        result: StageResult,
        env: Mapping[str, str],
        log,
    ) -> CommandResult:
        command_text = shlex.join(command)
        print(f"[{stage.name}] $ {command_text}")
        log.write(f"$ {command_text}\n")

        try:
            completed = self.run_command(command, cwd=stage.path, env=env)
        except subprocess.TimeoutExpired as exc:
            raise MigrationUpgradeError(f"Stage {stage.name!r} command timed out: {command_text}") from exc
        except OSError as exc:
            raise MigrationUpgradeError(f"Stage {stage.name!r} command could not be started: {command_text}") from exc
        output = f"{completed.stdout or ''}{completed.stderr or ''}"
        if output:
            print(output, end="")
            log.write(output)
        log.flush()

        if completed.returncode:
            raise MigrationUpgradeError(f"Stage {stage.name!r} command failed with exit code {completed.returncode}: {command_text}")
        return completed

    def _write_summary_best_effort(self) -> None:
        try:
            self._write_summary()
        except Exception as exc:
            print(f"Unable to write migration upgrade summary: {exc}", file=sys.stderr)

    def _write_summary(self) -> None:
        lines = [
            "# Migration upgrade validation",
            "",
            (
                "VCS revisions and resolved commits are recorded without repository URLs. Version tags can move between runs; "
                "only a full commit SHA pins the exact source revision."
            ),
            "",
        ]
        if self.snapshot_cleanup_warning:
            lines.append(f"- Warning: {self.snapshot_cleanup_warning}")
            lines.append("")
        for result in self.results:
            lines.extend(
                [
                    f"## {result.name}",
                    f"- Checkout: `{result.path}`",
                    f"- SHA: `{result.sha}`",
                    f"- Status: **{result.status}**",
                    f"- Log: `{result.log_path.name}`",
                ]
            )
            if result.error:
                lines.append(f"- Error: `{result.error}`")
            if result.inventory_path is not None:
                lines.append(f"- Inventory: `{result.inventory_path.name}`")
            if result.snapshot_result is not None:
                lines.append(f"- Snapshot round-trip: **{result.snapshot_result.get('status', 'unknown')}**")
                dump_sha256 = result.snapshot_result.get("dump_sha256")
                if isinstance(dump_sha256, str):
                    lines.append(f"- Snapshot dump SHA-256: `{dump_sha256}`")
            if result.snapshot_diagnostic_path is not None and result.snapshot_diagnostic_path.is_file():
                lines.append(f"- Snapshot diagnostics: `{result.snapshot_diagnostic_path.name}`")
            if result.fixture_snapshot_path is not None and result.fixture_snapshot_path.is_file():
                lines.append("- Fixed fixture identity: verified")
            if result.inventory is not None:
                lines.append(f"- Available migrations: `{len(result.inventory.get('available', {}))}`")
                lines.append(f"- Applied migrations: `{len(result.inventory.get('applied', []))}`")
                vcs_dependencies = result.inventory.get("vcs_dependencies", [])
                lines.append(f"- VCS dependencies: `{len(vcs_dependencies)}`")
                for dependency in vcs_dependencies:
                    requested_revision = dependency.get("requested_revision") or "unspecified"
                    if dependency.get("editable"):
                        requested_revision = f"{requested_revision} (editable)"
                    lines.append(f"  - `{dependency['distribution']}` requested `{requested_revision}`, resolved `{dependency['commit_id']}`")
            for policy_exception in result.policy_exceptions:
                lines.append(f"- Allowed policy exception: `{policy_exception}`")
            lines.append("")
        (self.output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        action="append",
        required=True,
        metavar="NAME=PATH",
        help="Ordered checkout to validate; repeat for each migration stage",
    )
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for logs and summary")
    parser.add_argument("--venv-root", type=Path, required=True, help="Directory for per-stage virtual environments")
    parser.add_argument("--policy", type=Path, required=True, help="Migration inventory policy JSON")
    parser.add_argument(
        "--snapshot-round-trip-after",
        action="append",
        default=[],
        metavar="STAGE",
        help="Opt in to a sanitized PostgreSQL dump/restore after the named stage",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if len(args.snapshot_round_trip_after) > 1:
        parser.error("--snapshot-round-trip-after may only be specified once")
    snapshot_round_trip_after = args.snapshot_round_trip_after[0] if args.snapshot_round_trip_after else None
    try:
        stages = [parse_stage_spec(spec) for spec in args.stage]
        MigrationUpgradeRunner(
            stages=stages,
            output_dir=args.output_dir,
            venv_root=args.venv_root,
            policy_path=args.policy,
            snapshot_round_trip_after=snapshot_round_trip_after,
        ).run()
    except (MigrationUpgradeError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
