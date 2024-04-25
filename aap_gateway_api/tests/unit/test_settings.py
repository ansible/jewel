import importlib

import pytest


@pytest.mark.parametrize(
    "redis_url",
    [
        "",
        "redis://localhost:6379/0",
    ],
)
def test_settings_redis_disabled_warning(capsys, env, redis_url):
    """
    Iff REDIS_URL is not set, a warning gets printed to stderr.
    """
    with env("REDIS_URL", redis_url):
        importlib.reload(importlib.import_module("aap_gateway_api.settings"))
        captured = capsys.readouterr()
        if not redis_url:
            assert "defaulting to memory cache" in captured.err
        else:
            assert "defaulting to memory cache" not in captured.err
