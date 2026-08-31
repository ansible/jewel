import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "tools" / "scripts" / "ci" / "tox-reinstall-django-ansible-base.sh"


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
    pip.write_text("#!/bin/sh\nexit 0\n")
    pip.chmod(pip.stat().st_mode | stat.S_IEXEC)
    return fake_bin


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
