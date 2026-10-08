#!/usr/bin/env python3
"""Run Django migrations through a sequence of gateway checkouts.

Each checkout gets its own virtual environment, while every migration command
uses the same database configured through the process environment.  This
exercises the upgrade path that a release branch will use in production.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

NOOP_MIGRATION_MESSAGE = "No migrations to apply."
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


CommandResult = subprocess.CompletedProcess[str]
RunCommand = Callable[..., CommandResult]
GitSha = Callable[[Path], str]


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
    )


def git_sha(path: Path) -> str:
    """Return the checked-out commit SHA for a stage."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
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
    ) -> None:
        self.stages = list(stages)
        self.output_dir = output_dir
        self.venv_root = venv_root
        self.run_command = run_command
        self.git_sha = git_sha
        self.base_env = dict(os.environ if base_env is None else base_env)
        self.python_executable = python_executable
        self.results: list[StageResult] = []

    def run(self) -> None:
        if not self.stages:
            raise MigrationUpgradeError("At least one migration upgrade stage is required")

        duplicate_names = sorted(name for name, count in Counter(stage.name for stage in self.stages).items() if count > 1)
        if duplicate_names:
            names = ", ".join(repr(name) for name in duplicate_names)
            raise MigrationUpgradeError(f"Duplicate migration stage names: {names}")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.venv_root.mkdir(parents=True, exist_ok=True)

        for stage in self.stages:
            result = StageResult(
                name=stage.name,
                path=stage.path,
                sha=self._stage_sha(stage),
                log_path=self.output_dir / f"{stage.name}.log",
            )
            self.results.append(result)

            try:
                self._run_stage(stage, result)
            except MigrationUpgradeError as exc:
                result.status = "failed"
                result.error = str(exc)
                self._write_summary()
                raise
            else:
                result.status = "passed"
                self._write_summary()

    def _stage_sha(self, stage: Stage) -> str:
        if not stage.path.is_dir():
            raise MigrationUpgradeError(f"Stage {stage.name!r} checkout does not exist: {stage.path}")
        try:
            return self.git_sha(stage.path)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise MigrationUpgradeError(f"Stage {stage.name!r} is not a git checkout: {stage.path}") from exc

    def _stage_env(self, stage: Stage, venv_dir: Path) -> dict[str, str]:
        env = dict(self.base_env)
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

        completed = self.run_command(command, cwd=stage.path, env=env)
        output = f"{completed.stdout or ''}{completed.stderr or ''}"
        if output:
            print(output, end="")
            log.write(output)
        log.flush()

        if completed.returncode:
            raise MigrationUpgradeError(f"Stage {stage.name!r} command failed with exit code {completed.returncode}: {command_text}")
        return completed

    def _write_summary(self) -> None:
        lines = ["# Migration upgrade validation", ""]
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        stages = [parse_stage_spec(spec) for spec in args.stage]
        MigrationUpgradeRunner(stages=stages, output_dir=args.output_dir, venv_root=args.venv_root).run()
    except (MigrationUpgradeError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
