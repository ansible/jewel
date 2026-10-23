import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[3] / "tools" / "scripts"))
import migration_upgrade  # noqa: E402
from ci.migration_inventory import MigrationPolicy  # noqa: E402

PUBLIC_POLICY = Path(__file__).parents[3] / "tools" / "configs" / "migration_upgrade_policy.json"


def completed(stdout="", returncode=0, stderr=""):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


def policy(**overrides):
    values = {
        "enforced_apps": frozenset({"aap_gateway_api"}),
        "allowed_missing": frozenset(),
        "allowed_fingerprint_changes": frozenset(),
        "immutable_vcs_stages": frozenset(),
    }
    values.update(overrides)
    return MigrationPolicy(**values)


def inventory(stage, *, available=None, applied=None, vcs_dependencies=None, checkout_sha="b" * 40):
    available = dict(available or {})
    return {
        "stage": stage,
        "checkout_sha": checkout_sha,
        "available": available,
        "applied": list(applied or []),
        "dependencies": {migration_key: [] for migration_key in available},
        "replacements": {migration_key: [] for migration_key in available},
        "vcs_dependencies": list(vcs_dependencies or []),
    }


def write_inventory_from_command(command, payload):
    output_path = Path(command[command.index("--output") + 1])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload), encoding="utf-8")


class TestCompareInventoryHistory:
    def test_reports_applied_migration_missing_from_same_stage(self):
        inventories = [inventory("release", applied=["aap_gateway_api.0001_initial"])]

        assert migration_upgrade.compare_inventory_history(inventories, policy()) == [
            migration_upgrade.InventoryViolation(
                kind="missing",
                stage="release",
                migration="aap_gateway_api.0001_initial",
                first_stage="release",
                first_fingerprint=None,
                current_fingerprint=None,
            )
        ]

    def test_reports_applied_migration_missing_from_later_stage(self):
        inventories = [
            inventory(
                "release",
                available={"aap_gateway_api.0001_initial": "first-sha"},
                applied=["aap_gateway_api.0001_initial"],
            ),
            inventory("later"),
        ]

        assert migration_upgrade.compare_inventory_history(inventories, policy()) == [
            migration_upgrade.InventoryViolation(
                kind="missing",
                stage="later",
                migration="aap_gateway_api.0001_initial",
                first_stage="release",
                first_fingerprint="first-sha",
                current_fingerprint=None,
            )
        ]

    def test_reports_changed_applied_migration_fingerprint(self):
        inventories = [
            inventory(
                "release",
                available={"aap_gateway_api.0001_initial": "first-sha"},
                applied=["aap_gateway_api.0001_initial"],
            ),
            inventory(
                "later",
                available={"aap_gateway_api.0001_initial": "changed-sha"},
                applied=["aap_gateway_api.0001_initial"],
            ),
        ]

        violations = migration_upgrade.compare_inventory_history(inventories, policy())

        assert violations == [
            migration_upgrade.InventoryViolation(
                kind="fingerprint",
                stage="later",
                migration="aap_gateway_api.0001_initial",
                first_stage="release",
                first_fingerprint="first-sha",
                current_fingerprint="changed-sha",
            )
        ]

    @pytest.mark.parametrize(
        ("policy_override", "current_available"),
        [
            ({"allowed_missing": frozenset({"aap_gateway_api.0001_initial"})}, {}),
            (
                {"allowed_fingerprint_changes": frozenset({"aap_gateway_api.0001_initial"})},
                {"aap_gateway_api.0001_initial": "changed-sha"},
            ),
        ],
    )
    def test_allows_explicit_policy_exception(self, policy_override, current_available):
        inventories = [
            inventory(
                "release",
                available={"aap_gateway_api.0001_initial": "first-sha"},
                applied=["aap_gateway_api.0001_initial"],
            ),
            inventory(
                "later",
                available=current_available,
                applied=["aap_gateway_api.0001_initial"],
            ),
        ]

        assert migration_upgrade.compare_inventory_history(inventories, policy(**policy_override)) == []

    def test_ignores_unenforced_application(self):
        inventories = [
            inventory("release", available={"dependency_app.0001_initial": "first"}, applied=["dependency_app.0001_initial"]),
            inventory("later"),
        ]

        assert migration_upgrade.compare_inventory_history(inventories, policy()) == []

    def test_allows_fingerprint_change_before_first_application(self):
        inventories = [
            inventory("release", available={"aap_gateway_api.0001_initial": "unapplied-sha"}),
            inventory(
                "pull-request",
                available={"aap_gateway_api.0001_initial": "applied-sha"},
                applied=["aap_gateway_api.0001_initial"],
            ),
            inventory(
                "later",
                available={"aap_gateway_api.0001_initial": "applied-sha"},
                applied=["aap_gateway_api.0001_initial"],
            ),
        ]

        assert migration_upgrade.compare_inventory_history(inventories, policy()) == []

    def test_uses_first_applied_fingerprint_for_later_comparison(self):
        inventories = [
            inventory("release", available={"aap_gateway_api.0001_initial": "unapplied-sha"}),
            inventory(
                "pull-request",
                available={"aap_gateway_api.0001_initial": "applied-sha"},
                applied=["aap_gateway_api.0001_initial"],
            ),
            inventory(
                "later",
                available={"aap_gateway_api.0001_initial": "changed-sha"},
                applied=["aap_gateway_api.0001_initial"],
            ),
        ]

        assert migration_upgrade.compare_inventory_history(inventories, policy()) == [
            migration_upgrade.InventoryViolation(
                kind="fingerprint",
                stage="later",
                migration="aap_gateway_api.0001_initial",
                first_stage="pull-request",
                first_fingerprint="applied-sha",
                current_fingerprint="changed-sha",
            )
        ]

    def test_reports_multiple_violations_deterministically(self):
        inventories = [
            inventory(
                "release",
                available={
                    "aap_gateway_api.0002_second": "second-sha",
                    "aap_gateway_api.0001_first": "first-sha",
                },
                applied=["aap_gateway_api.0002_second", "aap_gateway_api.0001_first"],
            ),
            inventory("later"),
        ]

        violations = migration_upgrade.compare_inventory_history(inventories, policy())

        assert [item.migration for item in violations] == [
            "aap_gateway_api.0001_first",
            "aap_gateway_api.0002_second",
        ]

    def test_lists_allowed_policy_exceptions(self):
        inventories = [
            inventory(
                "release",
                available={"aap_gateway_api.0001_initial": "first-sha"},
                applied=["aap_gateway_api.0001_initial"],
            ),
            inventory("later", applied=["aap_gateway_api.0001_initial"]),
        ]

        exceptions = migration_upgrade.find_policy_exceptions(
            inventories,
            policy(allowed_missing=frozenset({"aap_gateway_api.0001_initial"})),
        )

        assert exceptions == ["later: allowed missing migration aap_gateway_api.0001_initial"]


class TestParseStage:
    def test_parse_stage_spec(self, tmp_path):
        stage = migration_upgrade.parse_stage_spec(f"release={tmp_path}")

        assert stage.name == "release"
        assert stage.path == tmp_path

    @pytest.mark.parametrize(
        "spec",
        ["=checkout", "release=", "release", "release/name=checkout", "release=one=two"],
    )
    def test_rejects_invalid_stage_spec(self, spec):
        with pytest.raises(ValueError):
            migration_upgrade.parse_stage_spec(spec)


def test_parser_requires_policy(capsys):
    parser = migration_upgrade.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--stage",
                "release=/tmp/release",
                "--output-dir",
                "/tmp/output",
                "--venv-root",
                "/tmp/venvs",
            ]
        )

    assert "--policy" in capsys.readouterr().err


def test_snapshot_option_is_optional_and_rejects_duplicate_values(capsys):
    parser = migration_upgrade.build_parser()
    base_args = ["--stage", "release=/tmp/release", "--output-dir", "/tmp/output", "--venv-root", "/tmp/venvs", "--policy", str(PUBLIC_POLICY)]

    parsed = parser.parse_args(base_args)
    assert parsed.snapshot_round_trip_after == []

    with pytest.raises(SystemExit):
        migration_upgrade.main(base_args + ["--snapshot-round-trip-after", "release", "--snapshot-round-trip-after", "release"])

    assert "only be specified once" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("stages", "snapshot_stage", "message"),
    [
        (["release", "devel"], "missing", "(?i)unknown migration stage"),
        (["release"], "release", "must leave at least one later stage"),
    ],
)
def test_snapshot_stage_validation_fails_before_setup(tmp_path, stages, snapshot_stage, message):
    stage_objects = []
    for stage_name in stages:
        stage_path = tmp_path / stage_name
        stage_path.mkdir()
        stage_objects.append(migration_upgrade.Stage(stage_name, stage_path))

    runner = migration_upgrade.MigrationUpgradeRunner(
        stages=stage_objects,
        output_dir=tmp_path / "output",
        venv_root=tmp_path / "venvs",
        run_command=lambda command, *, cwd, env: pytest.fail("runner started before validating snapshot stage"),
        git_sha=lambda path: "b" * 40,
        base_env={},
        policy_path=PUBLIC_POLICY,
        snapshot_round_trip_after=snapshot_stage,
    )

    with pytest.raises(migration_upgrade.MigrationUpgradeError, match=message):
        runner.run()

    assert not (tmp_path / "output").exists()


def snapshot_runner(
    tmp_path,
    *,
    failure=None,
    restored_state=None,
    later_fixture=None,
    database_name="gw_migration_snapshot_aaaaaaaaaaaaaaaa",
):
    stages = []
    for stage_name in ("release", "devel"):
        stage_path = tmp_path / stage_name
        stage_path.mkdir()
        stages.append(migration_upgrade.Stage(stage_name, stage_path))

    fixture = {
        "organization": {"id": "12", "name": "Migration CI Snapshot Organization"},
        "team": {"id": "18", "name": "Migration CI Snapshot Team", "organization_id": "12"},
    }
    source_state = {
        "table_counts": {"aap_gateway_api_organization": 1},
        "applied_migrations": ["aap_gateway_api.0001_initial"],
        "fixture": fixture,
    }
    restored_state = source_state if restored_state is None else restored_state
    calls = []
    state_calls = 0

    def fake_run(command, *, cwd, env):
        nonlocal state_calls
        calls.append({"command": list(command), "cwd": cwd, "env": dict(env)})
        if str(command[1]).endswith("migration_inventory.py"):
            stage_name = command[command.index("--stage") + 1]
            checkout_sha = command[command.index("--checkout-sha") + 1]
            write_inventory_from_command(command, inventory(stage_name, checkout_sha=checkout_sha))
            return completed("inventory written\n")
        if str(command[1]).endswith("migration_snapshot_fixture.py"):
            action = command[2]
            if action == "validate-connection":
                if failure == "connection_preflight" and env.get("GATEWAY_DATABASES__default__HOST") == "remote.example.invalid":
                    return completed(returncode=6, stderr="effective database configuration is not local")
                return completed("Validated local PostgreSQL migration database configuration\n")
            if action == "state":
                payload = source_state if state_calls == 0 else restored_state
                state_calls += 1
                output_path = Path(command[command.index("--output") + 1])
                if not (failure == "state_missing" and state_calls == 1):
                    output_path.write_text(json.dumps({"invalid": True} if failure == "state_invalid" and state_calls == 1 else payload), encoding="utf-8")
            elif action == "snapshot":
                output_path = Path(command[command.index("--output") + 1])
                if later_fixture == "invalid":
                    output_path.write_text("{invalid", encoding="utf-8")
                elif later_fixture != "missing":
                    output_path.write_text(json.dumps(later_fixture or fixture), encoding="utf-8")
            return completed("snapshot helper finished\n")
        executable = Path(command[0]).name
        if executable == "pg_dump":
            if failure == "pg_dump_oserror":
                raise OSError("database credentials")
            if failure == "dropdb_exception":
                return completed(returncode=2, stderr="unit-test-password https://example.invalid/database")
            if failure == "pg_dump_timeout":
                raise subprocess.TimeoutExpired(command, timeout=1)
            if failure != "pg_dump_no_file":
                dump_path = Path(command[command.index("--file") + 1])
                dump_path.write_bytes(b"synthetic database dump bytes")
            if failure == "pg_dump":
                return completed(returncode=2, stderr="unit-test-password https://example.invalid/database")
        if executable == "createdb" and failure == "createdb":
            return completed(returncode=3, stderr="unit-test-password https://example.invalid/database")
        if executable == "pg_restore" and failure == "pg_restore":
            return completed(returncode=4, stderr="unit-test-password https://example.invalid/database")
        if executable == "dropdb" and failure == "pg_dump":
            return completed(returncode=9, stderr="cleanup failed: unit-test-password https://example.invalid/database")
        if executable == "dropdb" and failure == "dropdb_exception":
            raise OSError("cleanup failure details")
        if cwd == tmp_path / "devel" and "migrate" in command and failure == "next_stage":
            return completed(returncode=5, stderr="migration failed")
        if cwd == tmp_path / "devel" and "migrate" in command and failure == "next_stage_oserror":
            raise OSError("database credentials")
        return completed("No migrations to apply.\n" if "migrate" in command else "")

    runner = migration_upgrade.MigrationUpgradeRunner(
        stages=stages,
        output_dir=tmp_path / "output",
        venv_root=tmp_path / "venvs",
        run_command=fake_run,
        git_sha=lambda path: "b" * 40,
        base_env={
            "DATABASE_ENGINE": "django.db.backends.postgresql",
            "DATABASE_NAME": "gw_db",
            "DATABASE_USER": "gw",
            "DATABASE_PASSWORD": "unit-test-password",
            "DATABASE_HOST": "127.0.0.1",
            "DATABASE_PORT": "5432",
        },
        policy_path=PUBLIC_POLICY,
        snapshot_round_trip_after="release",
        snapshot_database_name_factory=lambda: database_name,
    )
    return runner, calls, source_state


def test_snapshot_round_trip_restores_state_and_switches_later_stages(tmp_path):
    runner, calls, source_state = snapshot_runner(tmp_path)
    runner.base_env.update(
        {
            "PGHOST": "database.example.invalid",
            "PGHOSTADDR": "198.51.100.10",
            "PGSERVICE": "remote-service",
            "PGSERVICEFILE": "/tmp/remote-service.conf",
            "PGPORT": "6432",
            "PGPASSWORD": "inherited-password",
        }
    )

    runner.run()

    commands = [call["command"] for call in calls]
    command_names = [Path(command[0]).name for command in commands]
    fixture_actions = [command[2] for command in commands if str(command[1]).endswith("migration_snapshot_fixture.py")]
    first_migrate_index = next(index for index, command in enumerate(commands) if "migrate" in command and "--noinput" in command)
    first_preflight_index = next(
        index for index, command in enumerate(commands) if str(command[1]).endswith("migration_snapshot_fixture.py") and command[2] == "validate-connection"
    )
    assert first_preflight_index < first_migrate_index
    assert fixture_actions.count("validate-connection") == 2
    assert command_names.index("pg_dump") < command_names.index("createdb") < command_names.index("pg_restore")
    assert (
        command_names.index("pg_restore")
        < [i for i, command in enumerate(commands) if str(command[1]).endswith("migration_snapshot_fixture.py") and command[2] == "state"][1]
    )
    assert "seed" in [command[2] for command in commands if str(command[1]).endswith("migration_snapshot_fixture.py")]
    pg_dump_call = calls[command_names.index("pg_dump")]
    assert pg_dump_call["command"][-1] == "gw_db"
    assert pg_dump_call["env"]["PGHOST"] == "127.0.0.1"
    assert pg_dump_call["env"]["PGPORT"] == "5432"
    assert pg_dump_call["env"]["PGPASSWORD"] == "unit-test-password"
    assert not {"PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"} & pg_dump_call["env"].keys()
    assert "unit-test-password" not in " ".join(pg_dump_call["command"])

    release_migrate = next(call for call in calls if call["cwd"] == tmp_path / "release" and "migrate" in call["command"] and "--noinput" in call["command"])
    assert release_migrate["env"]["PGHOST"] == "127.0.0.1"
    assert release_migrate["env"]["PGDATABASE"] == "gw_db"
    assert not {"PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"} & release_migrate["env"].keys()

    later_migrate = next(call for call in calls if call["cwd"] == tmp_path / "devel" and "migrate" in call["command"] and "--noinput" in call["command"])
    assert later_migrate["env"]["DATABASE_NAME"] == "gw_migration_snapshot_aaaaaaaaaaaaaaaa"
    assert later_migrate["env"]["PGDATABASE"] == "gw_migration_snapshot_aaaaaaaaaaaaaaaa"
    assert runner.snapshot_database_name is None
    assert not list(tmp_path.rglob("*.dump"))
    assert (tmp_path / "output" / "snapshot-round-trip.json").is_file()
    assert json.loads((tmp_path / "output" / "snapshot-round-trip.json").read_text(encoding="utf-8"))["source"] == source_state
    assert any(Path(command[0]).name == "dropdb" for command in commands)

    all_diagnostics = "\n".join(path.read_text(encoding="utf-8") for path in (tmp_path / "output").iterdir() if path.is_file())
    assert "synthetic database dump bytes" not in all_diagnostics
    assert "unit-test-password" not in all_diagnostics
    assert "https://example.invalid/database" not in all_diagnostics


def test_snapshot_effective_database_preflight_stops_before_migration(tmp_path):
    runner, calls, _ = snapshot_runner(tmp_path, failure="connection_preflight")
    runner.base_env["GATEWAY_DATABASES__default__HOST"] = "remote.example.invalid"

    with pytest.raises(migration_upgrade.MigrationUpgradeError, match="command failed with exit code 6"):
        runner.run()

    assert any(str(call["command"][1]).endswith("migration_snapshot_fixture.py") and call["command"][2] == "validate-connection" for call in calls)
    assert not any("migrate" in call["command"] for call in calls)
    assert not any(Path(call["command"][0]).name in {"pg_dump", "createdb", "pg_restore"} for call in calls)


def test_snapshot_cleans_database_when_later_stage_command_cannot_start(tmp_path):
    runner, calls, _ = snapshot_runner(tmp_path, failure="next_stage_oserror")

    with pytest.raises(migration_upgrade.MigrationUpgradeError, match="could not be started") as error:
        runner.run()

    assert "database credentials" not in str(error.value)
    assert any(Path(call["command"][0]).name == "dropdb" for call in calls)
    assert runner.snapshot_database_name is None
    assert not list(tmp_path.rglob("*.dump"))


@pytest.mark.parametrize("failure", ["pg_dump", "createdb", "pg_restore", "comparison", "next_stage", "later_fixture"])
def test_snapshot_failures_clean_dump_and_best_effort_database(tmp_path, failure):
    restored_state = None
    if failure == "comparison":
        restored_state = {
            "table_counts": {"aap_gateway_api_organization": 2},
            "applied_migrations": ["aap_gateway_api.0001_initial"],
            "fixture": {
                "organization": {"id": "12", "name": "Migration CI Snapshot Organization"},
                "team": {"id": "18", "name": "Migration CI Snapshot Team", "organization_id": "12"},
            },
        }
    later_fixture = None
    if failure == "later_fixture":
        later_fixture = {
            "organization": {"id": "99", "name": "Migration CI Snapshot Organization"},
            "team": {"id": "18", "name": "Migration CI Snapshot Team", "organization_id": "99"},
        }
    runner, calls, _ = snapshot_runner(tmp_path, failure=failure, restored_state=restored_state, later_fixture=later_fixture)

    with pytest.raises(migration_upgrade.MigrationUpgradeError) as error:
        runner.run()

    commands = [call["command"] for call in calls]
    assert any(Path(command[0]).name == "dropdb" for command in commands)
    assert not list(tmp_path.rglob("*.dump"))
    diagnostics = "\n".join(path.read_text(encoding="utf-8") for path in (tmp_path / "output").iterdir() if path.is_file())
    assert "synthetic database dump bytes" not in diagnostics
    assert "unit-test-password" not in diagnostics
    assert "https://example.invalid/database" not in diagnostics
    if failure == "pg_dump":
        assert "Snapshot pg_dump failed" in str(error.value)
        assert "cleanup failed" not in str(error.value)


def test_snapshot_rejects_unsafe_generated_database_names(tmp_path):
    runner, calls, _ = snapshot_runner(tmp_path, database_name="gw_snapshot;drop database")

    with pytest.raises(migration_upgrade.MigrationUpgradeError, match="(?i)generated snapshot database name is invalid"):
        runner.run()

    assert not any(Path(call["command"][0]).name in {"pg_dump", "createdb", "pg_restore"} for call in calls)


def test_snapshot_requires_database_name(tmp_path):
    runner, _, _ = snapshot_runner(tmp_path)
    runner.base_env.pop("DATABASE_NAME")

    with pytest.raises(migration_upgrade.MigrationUpgradeError, match="simple DATABASE_NAME identifier"):
        runner.run()


@pytest.mark.parametrize(
    ("environment_key", "environment_value", "message"),
    [
        ("DATABASE_ENGINE", "django.db.backends.sqlite3", "requires a PostgreSQL database engine"),
        ("DATABASE_HOST", "database.example.invalid", "restricted to a local PostgreSQL database"),
        ("DATABASE_NAME", "postgresql://example.invalid/database", "simple DATABASE_NAME identifier"),
    ],
)
def test_snapshot_refuses_nonlocal_or_nonpostgres_databases(tmp_path, environment_key, environment_value, message):
    runner, calls, _ = snapshot_runner(tmp_path)
    runner.base_env[environment_key] = environment_value

    with pytest.raises(migration_upgrade.MigrationUpgradeError, match=message):
        runner.run()

    assert not any(Path(call["command"][0]).name in {"pg_dump", "createdb", "pg_restore"} for call in calls)


def test_snapshot_dump_file_must_be_created(tmp_path):
    runner, calls, _ = snapshot_runner(tmp_path, failure="pg_dump_no_file")

    with pytest.raises(migration_upgrade.MigrationUpgradeError, match="did not create a dump"):
        runner.run()

    assert any(Path(call["command"][0]).name == "dropdb" for call in calls)


@pytest.mark.parametrize("failure", ["pg_dump_oserror", "pg_dump_timeout", "dropdb_exception", "state_missing", "state_invalid"])
def test_snapshot_wraps_command_and_state_errors_without_leaking_details(tmp_path, failure):
    runner, _, _ = snapshot_runner(tmp_path, failure=failure)

    with pytest.raises(migration_upgrade.MigrationUpgradeError) as error:
        runner.run()

    assert "unit-test-password" not in str(error.value)
    assert "example.invalid" not in str(error.value)
    diagnostics = "\n".join(path.read_text(encoding="utf-8") for path in (tmp_path / "output").iterdir() if path.is_file())
    assert "unit-test-password" not in diagnostics
    assert "example.invalid" not in diagnostics


def test_snapshot_cleanup_error_does_not_override_prior_failure(tmp_path):
    runner, _, _ = snapshot_runner(tmp_path, failure="dropdb_exception")

    with pytest.raises(migration_upgrade.MigrationUpgradeError, match="Snapshot pg_dump failed"):
        runner.run()


def test_snapshot_database_is_cleaned_when_later_checkout_sha_fails(tmp_path):
    runner, calls, _ = snapshot_runner(tmp_path)

    def fail_later_checkout(path):
        if path.name == "devel":
            raise subprocess.CalledProcessError(1, ["git", "rev-parse"])
        return "b" * 40

    runner.git_sha = fail_later_checkout

    with pytest.raises(migration_upgrade.MigrationUpgradeError, match="not a git checkout"):
        runner.run()

    assert any(Path(call["command"][0]).name == "dropdb" for call in calls)
    assert runner.snapshot_database_name is None
    summary = (tmp_path / "output" / "summary.md").read_text(encoding="utf-8")
    assert "## devel" in summary
    assert "Status: **failed**" in summary


def test_snapshot_dump_deletion_failure_fails_closed(tmp_path, monkeypatch):
    runner, _, _ = snapshot_runner(tmp_path)
    original_unlink = Path.unlink

    def fail_dump_unlink(path, *args, **kwargs):
        if path.suffix == ".dump" and path.is_file():
            raise OSError("dump cleanup failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_dump_unlink)

    with pytest.raises(migration_upgrade.MigrationUpgradeError, match="Unable to remove the temporary snapshot dump"):
        runner.run()

    diagnostics = json.loads((tmp_path / "output" / "snapshot-round-trip.json").read_text(encoding="utf-8"))
    assert diagnostics["status"] == "failed"


def test_snapshot_diagnostic_write_errors_are_sanitized(tmp_path, monkeypatch):
    runner, _, _ = snapshot_runner(tmp_path)
    monkeypatch.setattr(runner, "_write_json_atomically", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("database credentials")))

    with pytest.raises(migration_upgrade.MigrationUpgradeError, match="sanitized diagnostics") as error:
        runner.run()

    assert "database credentials" not in str(error.value)


def test_snapshot_rejects_database_name_factory_error(tmp_path):
    runner, _, _ = snapshot_runner(tmp_path)
    runner.snapshot_database_name_factory = lambda: (_ for _ in ()).throw(RuntimeError("sensitive detail"))

    with pytest.raises(migration_upgrade.MigrationUpgradeError, match="Unable to generate a snapshot database name") as error:
        runner.run()

    assert "sensitive detail" not in str(error.value)


@pytest.mark.parametrize("later_fixture", ["missing", "invalid"])
def test_later_stage_snapshot_errors_are_safe(tmp_path, later_fixture):
    runner, _, _ = snapshot_runner(tmp_path, later_fixture=later_fixture)

    with pytest.raises(migration_upgrade.MigrationUpgradeError, match="snapshot helper"):
        runner.run()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("not_object", "invalid state shape"),
        ("missing_file", "valid state JSON"),
        ("table_counts", "invalid table counts"),
        ("table_name", "invalid table counts"),
        ("count", "invalid table counts"),
        ("applied_migrations", "invalid applied migration keys"),
        ("migration_key", "invalid applied migration keys"),
        ("fixture", "invalid fixture identity"),
        ("organization_id", "invalid fixture identity"),
        ("team_relationship", "invalid fixture identity"),
    ],
)
def test_snapshot_state_validator_rejects_malformed_payloads(tmp_path, mutation, message):
    runner, _, source_state = snapshot_runner(tmp_path)
    payload = json.loads(json.dumps(source_state))
    if mutation == "not_object":
        payload = []
    elif mutation == "missing_file":
        payload = None
    elif mutation == "table_counts":
        payload["table_counts"] = []
    elif mutation == "table_name":
        payload["table_counts"] = {"bad;table": 1}
    elif mutation == "count":
        payload["table_counts"] = {"valid_table": True}
    elif mutation == "applied_migrations":
        payload["applied_migrations"] = "not-an-array"
    elif mutation == "migration_key":
        payload["applied_migrations"] = ["bad key"]
    elif mutation == "fixture":
        payload["fixture"] = []
    elif mutation == "organization_id":
        payload["fixture"]["organization"]["id"] = "bad/id"
    elif mutation == "team_relationship":
        payload["fixture"]["team"]["organization_id"] = "99"
    state_path = tmp_path / "state.json"
    if mutation != "missing_file":
        state_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(migration_upgrade.MigrationUpgradeError, match=message):
        runner._read_state_snapshot(state_path)


class TestMigrationUpgradeRunner:
    def test_rejects_duplicate_stage_names_before_setup(self, tmp_path):
        output_dir = tmp_path / "output"
        venv_root = tmp_path / "venvs"
        calls = []

        runner = migration_upgrade.MigrationUpgradeRunner(
            stages=[
                migration_upgrade.Stage("release", tmp_path / "first"),
                migration_upgrade.Stage("release", tmp_path / "second"),
            ],
            output_dir=output_dir,
            venv_root=venv_root,
            run_command=lambda command, *, cwd, env: calls.append((command, cwd, env)),
            base_env={},
            policy_path=PUBLIC_POLICY,
        )

        with pytest.raises(migration_upgrade.MigrationUpgradeError, match="Duplicate migration stage names"):
            runner.run()

        assert calls == []
        assert not output_dir.exists()
        assert not venv_root.exists()

    def test_preserves_stage_error_when_summary_write_fails(self, tmp_path, monkeypatch):
        stage_path = tmp_path / "release"
        stage_path.mkdir()
        runner = migration_upgrade.MigrationUpgradeRunner(
            stages=[migration_upgrade.Stage("release", stage_path)],
            output_dir=tmp_path / "output",
            venv_root=tmp_path / "venvs",
            run_command=lambda command, *, cwd, env: completed(returncode=1),
            git_sha=lambda path: "b" * 40,
            base_env={},
            policy_path=PUBLIC_POLICY,
        )

        def fail_summary():
            raise OSError("disk full")

        monkeypatch.setattr(runner, "_write_summary", fail_summary)

        with pytest.raises(migration_upgrade.MigrationUpgradeError, match="command failed"):
            runner.run()

    def test_runs_each_stage_in_order_and_requires_noop_migration(self, tmp_path):
        stage_path = tmp_path / "release"
        stage_path.mkdir()
        output_dir = tmp_path / "output"
        venv_root = tmp_path / "venvs"
        calls = []
        responses = iter(
            [
                completed(),  # create the virtualenv
                completed(),  # install the stage dependencies
                completed("migrations applied\n"),
                completed(),  # migrate --check
                completed("planned migrations\n"),
                completed("aap_gateway_api.0001_initial\n"),
                completed("No migrations to apply.\n"),
            ]
        )

        def fake_run(command, *, cwd, env):
            calls.append((command, cwd, env))
            if str(command[1]).endswith("migration_inventory.py"):
                write_inventory_from_command(
                    command,
                    inventory(
                        "release",
                        available={"aap_gateway_api.0001_initial": "c" * 64},
                        applied=["aap_gateway_api.0001_initial"],
                    ),
                )
                return completed("inventory written\n")
            return next(responses)

        runner = migration_upgrade.MigrationUpgradeRunner(
            stages=[migration_upgrade.Stage("release", stage_path)],
            output_dir=output_dir,
            venv_root=venv_root,
            run_command=fake_run,
            git_sha=lambda path: "b" * 40,
            base_env={"DATABASE_NAME": "gw_db", "GATEWAY_SECRET_KEY_FILE": "/tmp/key"},
            policy_path=PUBLIC_POLICY,
        )

        runner.run()

        assert [call[0][3:5] for call in calls[2:7]] == [
            ["migrate", "--noinput"],
            ["migrate", "--check"],
            ["showmigrations", "--plan"],
            ["shell", "-c"],
            ["migrate", "--noinput"],
        ]
        inventory_command = calls[7][0]
        assert str(inventory_command[1]).endswith("migration_inventory.py")
        assert str(inventory_command[1]).startswith(str(venv_root / "_helpers"))
        assert inventory_command[2:6] == ["--stage", "release", "--checkout-sha", "b" * 40]
        assert all(call[1] == stage_path for call in calls[1:])
        assert calls[2][2]["DATABASE_NAME"] == "gw_db"
        assert calls[2][2]["GATEWAY_SECRET_KEY_FILE"] == "/tmp/key"
        assert calls[2][2]["PATH"].startswith(f"{venv_root / 'release' / 'bin'}:")

        summary = (output_dir / "summary.md").read_text()
        assert "b" * 40 in summary
        assert "passed" in summary
        assert "release.inventory.json" in summary
        assert "Available migrations: `1`" in summary
        assert "Applied migrations: `1`" in summary
        assert (output_dir / "release.log").exists()
        assert (output_dir / "release.inventory.json").exists()
        assert (venv_root / "_helpers" / "migration_inventory.py").exists()
        assert "/tmp/key" not in summary

    def test_fails_when_second_migration_is_not_a_noop(self, tmp_path):
        stage_path = tmp_path / "release"
        stage_path.mkdir()
        responses = iter(
            [
                completed(),
                completed(),
                completed(),
                completed(),
                completed(),
                completed(),
                completed("Applying migration 0002\n"),
            ]
        )

        runner = migration_upgrade.MigrationUpgradeRunner(
            stages=[migration_upgrade.Stage("release", stage_path)],
            output_dir=tmp_path / "output",
            venv_root=tmp_path / "venvs",
            run_command=lambda command, *, cwd, env: next(responses),
            git_sha=lambda path: "release-sha",
            base_env={},
            policy_path=PUBLIC_POLICY,
        )

        with pytest.raises(migration_upgrade.MigrationUpgradeError, match="no-op"):
            runner.run()

        summary = (tmp_path / "output" / "summary.md").read_text()
        assert "failed" in summary


def single_stage_runner(tmp_path, collector_action, *, policy_path=PUBLIC_POLICY):
    stage_path = tmp_path / "release"
    stage_path.mkdir()
    responses = iter(
        [
            completed(),
            completed(),
            completed(),
            completed(),
            completed(),
            completed(),
            completed("No migrations to apply.\n"),
        ]
    )

    def fake_run(command, *, cwd, env):
        if str(command[1]).endswith("migration_inventory.py"):
            return collector_action(command)
        return next(responses)

    runner = migration_upgrade.MigrationUpgradeRunner(
        stages=[migration_upgrade.Stage("release", stage_path)],
        output_dir=tmp_path / "output",
        venv_root=tmp_path / "venvs",
        run_command=fake_run,
        git_sha=lambda path: "b" * 40,
        base_env={},
        policy_path=policy_path,
    )
    return runner


class TestInventoryRunnerFailures:
    def test_fails_when_inventory_command_fails(self, tmp_path):
        runner = single_stage_runner(tmp_path, lambda command: completed(returncode=7))

        with pytest.raises(migration_upgrade.MigrationUpgradeError, match="migration_inventory.py"):
            runner.run()

        assert "failed" in (tmp_path / "output" / "summary.md").read_text()

    def test_fails_when_collector_does_not_write_inventory(self, tmp_path):
        runner = single_stage_runner(tmp_path, lambda command: completed())

        with pytest.raises(migration_upgrade.MigrationUpgradeError, match="did not produce inventory"):
            runner.run()

    def test_fails_when_collector_writes_invalid_json(self, tmp_path):
        def invalid_json(command):
            output_path = Path(command[command.index("--output") + 1])
            output_path.write_text("{invalid", encoding="utf-8")
            return completed()

        runner = single_stage_runner(tmp_path, invalid_json)

        with pytest.raises(migration_upgrade.MigrationUpgradeError, match="invalid inventory JSON"):
            runner.run()

    @pytest.mark.parametrize(
        ("payload_update", "message"),
        [
            ({"available": []}, "available must be an object"),
            ({"applied": "aap_gateway_api.0001_initial"}, "applied must be an array"),
            ({"stage": "another-stage"}, "stage does not match"),
            ({"checkout_sha": "different-sha"}, "checkout SHA does not match"),
            ({"available": {"aap_gateway_api.0001_initial": "not-a-fingerprint"}}, "invalid fingerprint"),
            ({"unexpected": "value"}, "unknown fields"),
        ],
    )
    def test_fails_closed_on_malformed_inventory_fields(self, tmp_path, payload_update, message):
        payload = inventory("release")
        payload.update(payload_update)

        def write_payload(command):
            write_inventory_from_command(command, payload)
            return completed()

        runner = single_stage_runner(tmp_path, write_payload)

        with pytest.raises(migration_upgrade.MigrationUpgradeError, match=message):
            runner.run()

        assert "failed" in (tmp_path / "output" / "summary.md").read_text()

    def test_fails_closed_on_policy_violation(self, tmp_path):
        def missing_applied(command):
            write_inventory_from_command(
                command,
                inventory("release", applied=["aap_gateway_api.0001_initial"]),
            )
            return completed()

        runner = single_stage_runner(tmp_path, missing_applied)

        with pytest.raises(migration_upgrade.MigrationUpgradeError, match="missing.*aap_gateway_api.0001_initial"):
            runner.run()

    def test_summary_lists_allowed_policy_exception(self, tmp_path):
        policy_path = tmp_path / "policy.json"
        policy_path.write_text(
            json.dumps(
                {
                    "enforced_apps": ["aap_gateway_api"],
                    "allowed_missing": ["aap_gateway_api.0001_initial"],
                    "allowed_fingerprint_changes": [],
                    "immutable_vcs_stages": [],
                }
            ),
            encoding="utf-8",
        )

        def missing_allowed(command):
            write_inventory_from_command(
                command,
                inventory("release", applied=["aap_gateway_api.0001_initial"]),
            )
            return completed()

        runner = single_stage_runner(tmp_path, missing_allowed, policy_path=policy_path)
        runner.run()

        summary = (tmp_path / "output" / "summary.md").read_text()
        assert "Allowed policy exception" in summary
        assert "release: allowed missing migration aap_gateway_api.0001_initial" in summary

    def test_rejects_mutable_vcs_reference_in_immutable_stage(self, tmp_path):
        policy_path = tmp_path / "policy.json"
        policy_path.write_text(
            json.dumps(
                {
                    "enforced_apps": ["aap_gateway_api"],
                    "allowed_missing": [],
                    "allowed_fingerprint_changes": [],
                    "immutable_vcs_stages": ["release"],
                }
            ),
            encoding="utf-8",
        )

        def branch_reference(command):
            write_inventory_from_command(
                command,
                inventory(
                    "release",
                    vcs_dependencies=[
                        {
                            "distribution": "Example Distribution",
                            "vcs": "git",
                            "requested_revision": "devel",
                            "commit_id": "b" * 40,
                            "editable": False,
                        }
                    ],
                ),
            )
            return completed()

        runner = single_stage_runner(tmp_path, branch_reference, policy_path=policy_path)

        with pytest.raises(migration_upgrade.MigrationUpgradeError, match="unsafe VCS dependency provenance"):
            runner.run()

        summary = (tmp_path / "output" / "summary.md").read_text()
        assert "requested revision must be a full Git SHA" in summary
        assert "failed" in summary

    def test_summary_records_safe_vcs_provenance_without_urls(self, tmp_path):
        def semantic_tag(command):
            write_inventory_from_command(
                command,
                inventory(
                    "release",
                    vcs_dependencies=[
                        {
                            "distribution": "Example Distribution",
                            "vcs": "git",
                            "requested_revision": "v1.2.3",
                            "commit_id": "c" * 40,
                            "editable": False,
                        }
                    ],
                ),
            )
            return completed()

        runner = single_stage_runner(tmp_path, semantic_tag)

        runner.run()

        summary = (tmp_path / "output" / "summary.md").read_text()
        assert "Example Distribution" in summary
        assert "requested `v1.2.3`" in summary
        assert "resolved `" + "c" * 40 + "`" in summary
        assert "Version tags can move between runs" in summary
        assert "https://" not in summary
