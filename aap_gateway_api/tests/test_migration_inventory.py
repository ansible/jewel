import hashlib
import re
from pathlib import Path

import pytest

from tools.scripts.ci.migration_inventory import build_inventory, validate_inventory


@pytest.mark.django_db
def test_inventory_matches_the_configured_django_migration_graph():
    repository_root = Path(__file__).parents[2]

    inventory = build_inventory(stage="integration", checkout_sha="a" * 40)
    validate_inventory(inventory, expected_stage="integration", expected_checkout_sha="a" * 40)

    gateway_migrations = {key: fingerprint for key, fingerprint in inventory["available"].items() if key.startswith("aap_gateway_api.")}
    assert "aap_gateway_api.0001_initial" in gateway_migrations
    assert re.fullmatch(r"[0-9a-f]{64}", gateway_migrations["aap_gateway_api.0001_initial"])
    assert "aap_gateway_api.0001_initial" in inventory["applied"]
    assert set(inventory["dependencies"]) == set(inventory["available"])
    assert set(inventory["replacements"]) == set(inventory["available"])

    migration_path = repository_root / "aap_gateway_api/migrations/0001_initial.py"
    assert gateway_migrations["aap_gateway_api.0001_initial"] == hashlib.sha256(migration_path.read_bytes()).hexdigest()
    for dependency in inventory["vcs_dependencies"]:
        assert "url" not in dependency
        assert dependency["commit_id"]
