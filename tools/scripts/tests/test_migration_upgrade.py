import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import migration_upgrade  # noqa: E402


def completed(stdout="", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)


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
        )

        with pytest.raises(migration_upgrade.MigrationUpgradeError, match="Duplicate migration stage names"):
            runner.run()

        assert calls == []
        assert not output_dir.exists()
        assert not venv_root.exists()

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
            return next(responses)

        runner = migration_upgrade.MigrationUpgradeRunner(
            stages=[migration_upgrade.Stage("release", stage_path)],
            output_dir=output_dir,
            venv_root=venv_root,
            run_command=fake_run,
            git_sha=lambda path: "release-sha",
            base_env={"DATABASE_NAME": "gw_db", "GATEWAY_SECRET_KEY_FILE": "/tmp/key"},
        )

        runner.run()

        assert [call[0][3:5] for call in calls[2:]] == [
            ["migrate", "--noinput"],
            ["migrate", "--check"],
            ["showmigrations", "--plan"],
            ["shell", "-c"],
            ["migrate", "--noinput"],
        ]
        assert all(call[1] == stage_path for call in calls[1:])
        assert calls[2][2]["DATABASE_NAME"] == "gw_db"
        assert calls[2][2]["GATEWAY_SECRET_KEY_FILE"] == "/tmp/key"
        assert calls[2][2]["PATH"].startswith(f"{venv_root / 'release' / 'bin'}:")

        summary = (output_dir / "summary.md").read_text()
        assert "release-sha" in summary
        assert "passed" in summary
        assert (output_dir / "release.log").exists()

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
        )

        with pytest.raises(migration_upgrade.MigrationUpgradeError, match="no-op"):
            runner.run()

        summary = (tmp_path / "output" / "summary.md").read_text()
        assert "failed" in summary
