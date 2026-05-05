import argparse
import inspect
import logging

import yaml
from dispatcherd.cli import CONTROL_ARG_SCHEMAS, _base_cli_parent, _build_command_data_from_args, _control_common_parent, _register_control_arguments
from dispatcherd.config import setup as dispatcherd_setup
from dispatcherd.factories import get_control_from_settings
from dispatcherd.service import control_tasks
from django.core.management.base import BaseCommand, CommandError, CommandParser

from aap_gateway_api.dispatch.config import get_dispatcherd_config

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Dispatcherd control commands"

    def add_arguments(self, parser: CommandParser) -> None:
        base_parent = _base_cli_parent()
        control_parent = _control_common_parent()
        parser._add_container_actions(base_parent)
        parser._add_container_actions(control_parent)

        subparsers = parser.add_subparsers(dest="command", metavar="command")
        subparsers.required = True
        shared_parents = [base_parent, control_parent]

        for command in control_tasks.__all__:
            func = getattr(control_tasks, command, None)
            doc = inspect.getdoc(func) or ""
            summary = doc.splitlines()[0] if doc else None
            command_parser = subparsers.add_parser(
                command,
                help=summary,
                description=doc,
                parents=shared_parents,
            )
            _register_control_arguments(command_parser, CONTROL_ARG_SCHEMAS.get(command))

    def handle(self, *args, **options) -> None:
        command = options.pop("command", None)
        if not command:
            raise CommandError("No dispatcher control command specified")

        for django_opt in ("verbosity", "traceback", "no_color", "force_color", "skip_checks", "settings", "pythonpath"):
            options.pop(django_opt, None)

        expected_replies = options.pop("expected_replies", 1)

        config = get_dispatcherd_config()
        dispatcherd_setup(config)

        schema_namespace = argparse.Namespace(**options)
        data = _build_command_data_from_args(schema_namespace, command)

        ctl = get_control_from_settings()
        returned = ctl.control_with_reply(command, data=data, expected_replies=expected_replies)

        if len(returned) < expected_replies:
            logger.error(f"Obtained only {len(returned)} of {expected_replies}")
            raise CommandError("dispatcherctl returned fewer replies than expected")

        self.stdout.write(yaml.safe_dump(returned, default_flow_style=False))
