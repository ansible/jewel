import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

CI_SCRIPTS = Path(__file__).resolve().parents[3] / "tools" / "scripts" / "ci"
SCRIPT = CI_SCRIPTS / "tox-reinstall-django-ansible-base.sh"
INSTALL_SCRIPT = CI_SCRIPTS / "install_django_venv.sh"

EXPECTED_DAB_INSTALL = "install --upgrade -r django-ansible-base/requirements/requirements_all.txt ./django-ansible-base/[jwt]"
HASHED_INSTALL = "install --require-hashes --no-cache-dir -r requirements/requirements.txt"
TEST_DEPS_INSTALL = "install psycopg[binary] -r requirements_test.txt"


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
    pip.write_text(
        "#!/bin/sh\n"
        'if [ -n "${FAKE_PIP_FAIL:-}" ]; then\n'
        "    exit 1\n"
        "fi\n"
        'if [ -n "${FAKE_PIP_LOG:-}" ]; then\n'
        '    printf "%s\\n" "$*" >> "$FAKE_PIP_LOG"\n'
        "fi\n"
        "exit 0\n"
    )
    pip.chmod(pip.stat().st_mode | stat.S_IEXEC)
    return fake_bin


def _run_script(
    script: Path,
    *args: str,
    cwd: Path,
    fake_bin: Path | None = None,
    pip_log: Path | None = None,
    pip_fail: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ}
    if fake_bin is not None:
        env["PATH"] = f"{fake_bin}{os.pathsep}{os.environ['PATH']}"
    if pip_log is not None:
        env["FAKE_PIP_LOG"] = str(pip_log)
    if pip_fail:
        env["FAKE_PIP_FAIL"] = "1"
    return subprocess.run(
        ["sh", str(script), *args],
        cwd=cwd,
        env=env,
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

    result = _run_script(SCRIPT, str(env_dir), cwd=repo, fake_bin=fake_bin)

    assert result.returncode == 0, result.stderr + result.stdout
    cache_file = env_dir / "django_ansible_base_requirements.txt"
    assert cache_file.read_text() == "cached-requirements\n"
    assert not (repo / ".tox").exists()


def test_skips_when_dab_git_is_missing(tmp_path):
    repo = _prepare_repo(tmp_path, with_dab_git=False)
    env_dir = tmp_path / "tox-cache" / "py312"
    env_dir.mkdir(parents=True)

    result = _run_script(SCRIPT, str(env_dir), cwd=repo)

    assert result.returncode == 0, result.stderr + result.stdout
    assert not (env_dir / "django_ansible_base_requirements.txt").exists()
    assert not (repo / ".tox").exists()


@pytest.mark.parametrize(
    "force",
    [False, True],
    ids=["cache-hit", "force"],
)
def test_cache_hit_respects_force_flag(tmp_path, force):
    repo = _prepare_repo(tmp_path)
    env_dir = tmp_path / "tox-cache" / "py312"
    env_dir.mkdir(parents=True)
    (env_dir / "django_ansible_base_requirements.txt").write_text("cached-requirements\n")
    fake_bin = _fake_pip(tmp_path)
    pip_log = tmp_path / "pip.log"

    args = ["--force", str(env_dir)] if force else [str(env_dir)]
    result = _run_script(SCRIPT, *args, cwd=repo, fake_bin=fake_bin, pip_log=pip_log)

    assert result.returncode == 0, result.stderr + result.stdout
    if force:
        assert pip_log.read_text().splitlines() == [EXPECTED_DAB_INSTALL]
    else:
        assert not pip_log.exists()
    assert (env_dir / "django_ansible_base_requirements.txt").read_text() == "cached-requirements\n"


def test_installs_dab_requirements_all_alongside_local_checkout(tmp_path):
    """The checkout's pinned deps must be installed, not just the loose pyproject constraints."""
    repo = _prepare_repo(tmp_path)
    env_dir = tmp_path / "tox-cache" / "py312"
    fake_bin = _fake_pip(tmp_path)
    pip_log = tmp_path / "pip.log"

    result = _run_script(SCRIPT, str(env_dir), cwd=repo, fake_bin=fake_bin, pip_log=pip_log)

    assert result.returncode == 0, result.stderr + result.stdout
    assert pip_log.read_text().splitlines() == [EXPECTED_DAB_INSTALL]


def test_force_without_extras_installs_local_dab_without_brackets(tmp_path):
    repo = _prepare_repo(tmp_path)
    (repo / "requirements" / "requirements_git.txt").write_text("django-ansible-base @ git+https://github.com/ansible/django-ansible-base@devel\n")
    env_dir = tmp_path / "tox-cache" / "py312"
    fake_bin = _fake_pip(tmp_path)
    pip_log = tmp_path / "pip.log"

    result = _run_script(SCRIPT, "--force", str(env_dir), cwd=repo, fake_bin=fake_bin, pip_log=pip_log)

    assert result.returncode == 0, result.stderr + result.stdout
    assert pip_log.read_text().splitlines() == ["install --upgrade -r django-ansible-base/requirements/requirements_all.txt ./django-ansible-base/"]


def test_pip_failure_exits_nonzero_and_skips_caching(tmp_path):
    repo = _prepare_repo(tmp_path)
    env_dir = tmp_path / "tox-cache" / "py312"
    fake_bin = _fake_pip(tmp_path)

    result = _run_script(SCRIPT, "--force", str(env_dir), cwd=repo, fake_bin=fake_bin, pip_fail=True)

    assert result.returncode != 0, result.stdout
    assert not (env_dir / "django_ansible_base_requirements.txt").exists()


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
    assert pip_log.read_text().splitlines() == [HASHED_INSTALL, TEST_DEPS_INSTALL, EXPECTED_DAB_INSTALL]


def test_install_script_skips_dab_reinstall_when_hashed_requirements_unchanged(tmp_path):
    repo = _prepare_install_repo(tmp_path)
    env_dir = tmp_path / "tox-cache" / "py312"
    fake_bin = _fake_pip(tmp_path)

    first = _run_script(
        repo / "tools" / "scripts" / "ci" / INSTALL_SCRIPT.name,
        str(env_dir),
        "-r",
        "requirements_test.txt",
        cwd=repo,
        fake_bin=fake_bin,
        pip_log=tmp_path / "first.log",
    )
    assert first.returncode == 0, first.stderr + first.stdout

    second_log = tmp_path / "second.log"
    second = _run_script(
        repo / "tools" / "scripts" / "ci" / INSTALL_SCRIPT.name,
        str(env_dir),
        "-r",
        "requirements_test.txt",
        cwd=repo,
        fake_bin=fake_bin,
        pip_log=second_log,
    )

    assert second.returncode == 0, second.stderr + second.stdout
    assert second_log.read_text().splitlines() == [HASHED_INSTALL, TEST_DEPS_INSTALL]


def test_install_script_forces_dab_reinstall_when_hashed_requirements_change(tmp_path):
    repo = _prepare_install_repo(tmp_path)
    env_dir = tmp_path / "tox-cache" / "py312"
    fake_bin = _fake_pip(tmp_path)

    first = _run_script(
        repo / "tools" / "scripts" / "ci" / INSTALL_SCRIPT.name,
        str(env_dir),
        "-r",
        "requirements_test.txt",
        cwd=repo,
        fake_bin=fake_bin,
        pip_log=tmp_path / "first.log",
    )
    assert first.returncode == 0, first.stderr + first.stdout

    (repo / "requirements" / "requirements.txt").write_text("different-hashed-requirements\n")
    second_log = tmp_path / "second.log"
    second = _run_script(
        repo / "tools" / "scripts" / "ci" / INSTALL_SCRIPT.name,
        str(env_dir),
        "-r",
        "requirements_test.txt",
        cwd=repo,
        fake_bin=fake_bin,
        pip_log=second_log,
    )

    assert second.returncode == 0, second.stderr + second.stdout
    assert second_log.read_text().splitlines() == [HASHED_INSTALL, TEST_DEPS_INSTALL, EXPECTED_DAB_INSTALL]


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
    assert pip_log.read_text().splitlines() == [
        HASHED_INSTALL,
        "install psycopg[binary] -r requirements/requirements_git.txt -r requirements_test.txt",
    ]
