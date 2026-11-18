import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

CI_SCRIPTS = Path(__file__).resolve().parents[3] / "tools" / "scripts" / "ci"
SCRIPT = CI_SCRIPTS / "tox-reinstall-django-ansible-base.sh"
INSTALL_SCRIPT = CI_SCRIPTS / "install_django_venv.sh"


def _prepare_repo(tmp_path: Path, *, with_dab_git: bool = True) -> Path:
    repo = tmp_path / "repo"
    dab = repo / "django-ansible-base"
    (dab / "requirements").mkdir(parents=True)
    if with_dab_git:
        (dab / ".git").mkdir()
    (dab / "requirements" / "requirements_all.txt").write_text("cached-requirements\n")
    (repo / "requirements").mkdir()
    (repo / "requirements" / "requirements_git.txt").write_text("django-ansible-base[jwt] @ git+https://github.com/ansible/django-ansible-base@devel\n")
    return repo


def _fake_pip(tmp_path: Path) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    pip = fake_bin / "pip"
    pip.write_text("#!/bin/sh\nif [ -n \"${FAKE_PIP_LOG:-}\" ]; then\n    printf \"%s\\n\" \"$*\" >> \"$FAKE_PIP_LOG\"\nfi\nexit 0\n")
    pip.chmod(pip.stat().st_mode | stat.S_IEXEC)
    return fake_bin


def _run_script(script: Path, *args: str, cwd: Path, fake_bin: Path, pip_log: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(script), *args],
        cwd=cwd,
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "FAKE_PIP_LOG": str(pip_log),
        },
        capture_output=True,
        text=True,
        check=False,
    )


def _prepare_install_repo(tmp_path: Path, *, with_dab_git: bool = True) -> Path:
    repo = _prepare_repo(tmp_path, with_dab_git=with_dab_git)
    (repo / "requirements" / "requirements.txt").write_text("hashed-requirements\n")
    scripts = repo / "tools" / "scripts" / "ci"
    scripts.mkdir(parents=True)
    shutil.copy(SCRIPT, scripts / SCRIPT.name)
    shutil.copy(INSTALL_SCRIPT, scripts / INSTALL_SCRIPT.name)
    return repo


@pytest.mark.parametrize(
    "env_dir_name",
    ["py312", "check-help-text"],
)
def test_caches_requirements_in_tox_envdir_not_dot_tox(tmp_path, env_dir_name):
    repo = _prepare_repo(tmp_path)
    env_dir = tmp_path / "tox-cache" / env_dir_name
    env_dir.mkdir(parents=True)
    fake_bin = _fake_pip(tmp_path)

    result = subprocess.run(
        ["sh", str(SCRIPT), str(env_dir)],
        cwd=repo,
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    cache_file = env_dir / "django_ansible_base_requirements.txt"
    assert cache_file.read_text() == "cached-requirements\n"
    assert not (repo / ".tox").exists()


def test_skips_when_dab_git_is_missing(tmp_path):
    repo = _prepare_repo(tmp_path, with_dab_git=False)
    env_dir = tmp_path / "tox-cache" / "py312"
    env_dir.mkdir(parents=True)

    result = subprocess.run(
        ["sh", str(SCRIPT), str(env_dir)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert not (env_dir / "django_ansible_base_requirements.txt").exists()
    assert not (repo / ".tox").exists()


def test_skips_when_cached_requirements_match(tmp_path):
    repo = _prepare_repo(tmp_path)
    env_dir = tmp_path / "tox-cache" / "py312"
    env_dir.mkdir(parents=True)
    (env_dir / "django_ansible_base_requirements.txt").write_text("cached-requirements\n")
    fake_bin = _fake_pip(tmp_path)
    pip_log = tmp_path / "pip.log"

    result = _run_script(SCRIPT, str(env_dir), cwd=repo, fake_bin=fake_bin, pip_log=pip_log)

    assert result.returncode == 0, result.stderr + result.stdout
    assert not pip_log.exists()


def test_force_reinstalls_and_upgrades_when_cached_requirements_match(tmp_path):
    repo = _prepare_repo(tmp_path)
    env_dir = tmp_path / "tox-cache" / "py312"
    env_dir.mkdir(parents=True)
    (env_dir / "django_ansible_base_requirements.txt").write_text("cached-requirements\n")
    fake_bin = _fake_pip(tmp_path)
    pip_log = tmp_path / "pip.log"

    result = _run_script(SCRIPT, "--force", str(env_dir), cwd=repo, fake_bin=fake_bin, pip_log=pip_log)

    assert result.returncode == 0, result.stderr + result.stdout
    calls = pip_log.read_text().splitlines()
    assert calls == ["install --upgrade ./django-ansible-base/[jwt]"]
    assert (env_dir / "django_ansible_base_requirements.txt").read_text() == "cached-requirements\n"


def test_force_without_extras_installs_local_dab_without_brackets(tmp_path):
    repo = _prepare_repo(tmp_path)
    (repo / "requirements" / "requirements_git.txt").write_text("django-ansible-base @ git+https://github.com/ansible/django-ansible-base@devel\n")
    env_dir = tmp_path / "tox-cache" / "py312"
    fake_bin = _fake_pip(tmp_path)
    pip_log = tmp_path / "pip.log"

    result = _run_script(SCRIPT, "--force", str(env_dir), cwd=repo, fake_bin=fake_bin, pip_log=pip_log)

    assert result.returncode == 0, result.stderr + result.stdout
    assert pip_log.read_text().splitlines() == ["install --upgrade ./django-ansible-base/"]


def test_install_script_applies_local_dab_after_hashed_requirements(tmp_path):
    repo = _prepare_install_repo(tmp_path)
    env_dir = tmp_path / "tox-cache" / "py312"
    fake_bin = _fake_pip(tmp_path)
    pip_log = tmp_path / "pip.log"

    result = _run_script(
        repo / "tools" / "scripts" / "ci" / INSTALL_SCRIPT.name,
        str(env_dir),
        "-r",
        "requirements_test.txt",
        cwd=repo,
        fake_bin=fake_bin,
        pip_log=pip_log,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    calls = pip_log.read_text().splitlines()
    assert calls == [
        "install --require-hashes --no-cache-dir -r requirements/requirements.txt",
        "install psycopg[binary] -r requirements_test.txt",
        "install --upgrade ./django-ansible-base/[jwt]",
    ]


def test_install_script_installs_dab_from_git_without_checkout(tmp_path):
    repo = _prepare_install_repo(tmp_path, with_dab_git=False)
    env_dir = tmp_path / "tox-cache" / "py312"
    fake_bin = _fake_pip(tmp_path)
    pip_log = tmp_path / "pip.log"

    result = _run_script(
        repo / "tools" / "scripts" / "ci" / INSTALL_SCRIPT.name,
        str(env_dir),
        "-r",
        "requirements_test.txt",
        cwd=repo,
        fake_bin=fake_bin,
        pip_log=pip_log,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    calls = pip_log.read_text().splitlines()
    assert calls == [
        "install --require-hashes --no-cache-dir -r requirements/requirements.txt",
        "install psycopg[binary] -r requirements/requirements_git.txt -r requirements_test.txt",
    ]
