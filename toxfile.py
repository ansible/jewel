"""Manage Podman test containers during tox runs."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from tox.config.loader.section import Section
from tox.config.sets import ConfigSet, EnvConfigSet
from tox.execute.api import Outcome
from tox.plugin import impl
from tox.session.state import State
from tox.tox_env.api import ToxEnv
from tox.tox_env.errors import Fail

LOGGER = logging.getLogger(__name__)
RUNNING_CONTAINERS: Dict[str, List[str]] = {}
VALID_ENVIRONMENT_VARIABLE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
PODMAN_EXECUTABLE = os.environ.get("PODMAN_EXECUTABLE", "podman")


class ExposedPort:
    """A container port whose published port is exported to the tox environment."""

    def __init__(self, value: str) -> None:
        environment_variable, separator, container_port = value.partition("=")
        if not separator:
            raise ValueError(f"{value!r} must use ENVIRONMENT_VARIABLE=PORT/PROTOCOL")
        if not VALID_ENVIRONMENT_VARIABLE.fullmatch(environment_variable):
            raise ValueError(f"{environment_variable!r} is not a valid environment variable")

        port, separator, protocol = container_port.partition("/")
        if not separator or not port.isdigit() or protocol not in {"tcp", "udp"}:
            raise ValueError(f"{container_port!r} is not a valid container port")

        self.environment_variable = environment_variable
        self.container_port = port
        self.protocol = protocol

    @property
    def value(self) -> str:
        return f"{self.container_port}/{self.protocol}"


class PodmanConfigSet(ConfigSet):
    """Configuration for a Podman container managed by tox."""

    def register_config(self) -> None:
        self.add_config(keys=["image"], of_type=str, default="", desc="image to run")
        self.add_config(
            keys=["environment"],
            of_type=Dict[str, str],
            default={},
            desc="environment variables passed to the container",
        )
        self.add_config(
            keys=["healthcheck_cmd"],
            of_type=str,
            default="",
            desc="command run in the container until it succeeds",
        )
        self.add_config(
            keys=["healthcheck_timeout"],
            of_type=float,
            default=5,
            desc="health check command timeout in seconds",
        )
        self.add_config(
            keys=["healthcheck_retries"],
            of_type=int,
            default=5,
            desc="number of health check attempts",
        )
        self.add_config(
            keys=["healthcheck_interval"],
            of_type=float,
            default=1,
            desc="seconds between health check attempts",
        )
        self.add_config(
            keys=["healthcheck_start_period"],
            of_type=float,
            default=0,
            desc="initial delay before health checks",
        )
        self.add_config(
            keys=["expose"],
            of_type=List[ExposedPort],
            default=[],
            desc="container ports to publish to the tox environment",
        )
        self.add_config(
            keys=["host_var"],
            of_type=str,
            default="",
            desc="environment variable assigned the container host",
        )


@dataclass(frozen=True)
class PodmanContainer:
    name: str
    image: str
    environment: Dict[str, str]
    healthcheck_cmd: str
    healthcheck_timeout: float
    healthcheck_retries: int
    healthcheck_interval: float
    healthcheck_start_period: float
    expose: List[ExposedPort]
    host_var: str


def container_name(tox_env: ToxEnv, config: PodmanContainer) -> str:
    env_name = re.sub(r"[^a-zA-Z0-9_.-]", "-", tox_env.conf["env_name"])
    return f"tox-podman-{config.name}-{env_name}-{os.getpid()}"


def run_podman(*args: str, timeout: Optional[float] = None) -> subprocess.CompletedProcess[str]:
    if not shutil.which(PODMAN_EXECUTABLE):
        raise Fail(f"Podman executable {PODMAN_EXECUTABLE!r} was not found; set PODMAN_EXECUTABLE to its absolute path")
    return subprocess.run(
        [PODMAN_EXECUTABLE, *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def published_port(name: str, exposed_port: ExposedPort) -> str:
    result = run_podman("port", name, exposed_port.value)
    address = result.stdout.strip().splitlines()[0]
    return address.rsplit(":", 1)[1]


def stop_container(name: str) -> None:
    try:
        run_podman("rm", "--force", name, timeout=10)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        LOGGER.debug("Unable to remove Podman test container %s", name, exc_info=True)


def clean_up(tox_env: ToxEnv) -> None:
    for name in RUNNING_CONTAINERS.pop(tox_env.conf["env_name"], []):
        stop_container(name)


def start_cleanup_watchdog(name: str) -> None:
    """Remove a container if tox exits before its teardown hook runs."""
    subprocess.Popen(
        [
            "sh",
            "-c",
            'while kill -0 "$1" 2>/dev/null; do sleep 1; done; "$2" rm --force "$3" >/dev/null 2>&1 || true',
            "tox-podman-watchdog",
            str(os.getpid()),
            PODMAN_EXECUTABLE,
            name,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def start_container(tox_env: ToxEnv, config: PodmanContainer) -> None:
    name = container_name(tox_env, config)
    args = [
        "run",
        "--detach",
        "--name",
        name,
        "--label",
        "io.tox-podman.managed=true",
        "--label",
        f"io.tox-podman.environment={tox_env.conf['env_name']}",
    ]
    for key, value in config.environment.items():
        args.extend(["--env", f"{key}={value}"])
    for exposed_port in config.expose:
        args.extend(["--publish", f"127.0.0.1::{exposed_port.value}"])
    args.append(config.image)

    LOGGER.warning("podman> run %s", config.image)
    run_podman(*args)
    RUNNING_CONTAINERS.setdefault(tox_env.conf["env_name"], []).append(name)
    start_cleanup_watchdog(name)


def wait_for_health(config: PodmanContainer, name: str) -> None:
    if not config.healthcheck_cmd:
        return

    time.sleep(config.healthcheck_start_period)
    for attempt in range(config.healthcheck_retries):
        try:
            run_podman(
                "exec",
                name,
                "sh",
                "-c",
                config.healthcheck_cmd,
                timeout=config.healthcheck_timeout,
            )
            return
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if attempt + 1 < config.healthcheck_retries:
                time.sleep(config.healthcheck_interval)

    raise Fail(f"{config.image!r} (from {config.name!r}) failed health check")


def export_connection(tox_env: ToxEnv, config: PodmanContainer, name: str) -> None:
    environment = {port.environment_variable: published_port(name, port) for port in config.expose}
    if config.host_var:
        environment[config.host_var] = "127.0.0.1"
    tox_env.conf["set_env"].update(environment)


def parse_container(config_set: PodmanConfigSet) -> PodmanContainer:
    if not config_set["image"]:
        raise ValueError(f"{config_set.name}: image is required")
    return PodmanContainer(
        name=config_set.name,
        image=config_set["image"],
        environment=config_set["environment"],
        healthcheck_cmd=config_set["healthcheck_cmd"],
        healthcheck_timeout=config_set["healthcheck_timeout"],
        healthcheck_retries=config_set["healthcheck_retries"],
        healthcheck_interval=config_set["healthcheck_interval"],
        healthcheck_start_period=config_set["healthcheck_start_period"],
        expose=config_set["expose"],
        host_var=config_set["host_var"],
    )


@impl
def tox_add_env_config(env_conf: EnvConfigSet, state: State) -> None:
    def build_podman_config_set(container_name: object) -> PodmanConfigSet:
        assert isinstance(container_name, str)
        return state.conf.get_section_config(
            section=Section("podman", container_name),
            base=[],
            of_type=PodmanConfigSet,
            for_env=None,
        )

    env_conf.add_config(
        keys=["podman"],
        of_type=List[PodmanConfigSet],
        default=[],
        desc="Podman container configurations to run during this tox environment",
        factory=build_podman_config_set,
    )


@impl
def tox_before_run_commands(tox_env: ToxEnv) -> None:
    for config_set in tox_env.conf.load("podman"):
        config = parse_container(config_set)
        name = container_name(tox_env, config)
        try:
            start_container(tox_env, config)
            wait_for_health(config, name)
            export_connection(tox_env, config, name)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            clean_up(tox_env)
            raise Fail(error.stderr or str(error)) from error
        except Exception:
            clean_up(tox_env)
            raise


@impl
def tox_after_run_commands(tox_env: ToxEnv, exit_code: int, outcomes: List[Outcome]) -> None:
    clean_up(tox_env)


@impl
def tox_env_teardown(tox_env: ToxEnv) -> None:
    clean_up(tox_env)
