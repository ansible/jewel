"""Tests for _initialize_tasks.py function signatures.

Verifies that all RunPython callback functions in _initialize_tasks.py
have the correct signature: (apps, _schema_editor). Django's RunPython
always passes both arguments positionally, so the parameter *name* is
irrelevant at runtime, but the arity must remain correct.

Uses AST parsing to avoid importing the module (which requires Django).
"""

import ast
import os

_MODULE_PATH = os.path.join(
    os.path.dirname(__file__),
    os.pardir,
    os.pardir,
    'migrations',
    '_initialize_tasks.py',
)

# All RunPython callbacks that Django invokes with (apps, schema_editor)
_RUNPYTHON_CALLBACKS = [
    'create_system_user',
    'create_permissions_as_operation',
    'create_default_service_types',
    'migrate_service_types',
    'update_service_ping_url',
    'change_outlier_detection_max_ejection_percent_from_33_to_100',
    'change_outlier_detection_max_ejection_percent_from_100_to_33',
]


def _parse_functions():
    """Parse the module with AST and return a dict of function_name -> list of param names."""
    with open(os.path.normpath(_MODULE_PATH)) as f:
        tree = ast.parse(f.read())
    functions = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            params = [arg.arg for arg in node.args.args]
            functions[node.name] = params
    return functions


class TestInitializeTasksSignatures:
    """Validate that RunPython callbacks have the correct two-parameter signature."""

    def test_all_callbacks_exist(self):
        """Every expected callback is defined in the module."""
        functions = _parse_functions()
        for name in _RUNPYTHON_CALLBACKS:
            assert name in functions, f"Missing function: {name}"

    def test_all_callbacks_accept_two_positional_args(self):
        """Each callback must accept exactly two positional arguments (apps, schema_editor)."""
        functions = _parse_functions()
        for name in _RUNPYTHON_CALLBACKS:
            params = functions[name]
            assert len(params) == 2, f"{name} should accept exactly 2 positional args, got {len(params)}: {params}"

    def test_schema_editor_param_is_underscore_prefixed(self):
        """The unused schema_editor parameter should be underscore-prefixed per python:S1172."""
        functions = _parse_functions()
        for name in _RUNPYTHON_CALLBACKS:
            params = functions[name]
            second_param = params[1]
            assert second_param.startswith('_'), (
                f"{name}: second parameter '{second_param}' should be underscore-prefixed to indicate it is intentionally unused"
            )

    def test_helper_function_has_three_params(self):
        """The helper function (not a RunPython callback) should have 3 params."""
        functions = _parse_functions()
        params = functions['change_outlier_detection_max_ejection_percent']
        assert len(params) == 3, f"Helper function should accept 3 positional args (apps, old, new), got {len(params)}"
