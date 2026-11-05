import json
import sys
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[3] / "tools" / "scripts" / "ci"))
import migration_inventory  # noqa: E402
from migration_inventory import (
    MigrationInventoryError,
    MigrationPolicy,
    build_inventory,
    load_policy,
    validate_inventory,
    validate_vcs_provenance,
    write_inventory,
)  # noqa: E402


def write_policy(tmp_path, payload):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def valid_policy(**overrides):
    payload = {
        "enforced_apps": ["aap_gateway_api"],
        "allowed_missing": [],
        "allowed_fingerprint_changes": [],
        "immutable_vcs_stages": [],
    }
    payload.update(overrides)
    return payload


def valid_inventory_payload():
    migration_key = "example_app.0001_initial"
    return {
        "stage": "release",
        "checkout_sha": "b" * 40,
        "available": {migration_key: "a" * 64},
        "applied": [],
        "dependencies": {migration_key: []},
        "replacements": {migration_key: []},
        "vcs_dependencies": [],
    }


def test_loads_empty_public_policy():
    repository_root = Path(__file__).parents[3]

    policy = load_policy(repository_root / "tools/configs/migration_upgrade_policy.json")

    assert policy == MigrationPolicy(
        enforced_apps=frozenset({"aap_gateway_api"}),
        allowed_missing=frozenset(),
        allowed_fingerprint_changes=frozenset(),
        immutable_vcs_stages=frozenset(),
    )


def test_loads_valid_multi_app_policy(tmp_path):
    path = write_policy(
        tmp_path,
        valid_policy(
            enforced_apps=["aap_gateway_api", "dab_rbac"],
            allowed_missing=["dab_rbac.0001_initial"],
            allowed_fingerprint_changes=["aap_gateway_api.0002_example"],
            immutable_vcs_stages=["published", "release-2.0"],
        ),
    )

    policy = load_policy(path)

    assert policy.enforced_apps == frozenset({"aap_gateway_api", "dab_rbac"})
    assert policy.allowed_missing == frozenset({"dab_rbac.0001_initial"})
    assert policy.allowed_fingerprint_changes == frozenset({"aap_gateway_api.0002_example"})
    assert policy.immutable_vcs_stages == frozenset({"published", "release-2.0"})


def test_rejects_missing_policy(tmp_path):
    with pytest.raises(MigrationInventoryError, match="does not exist"):
        load_policy(tmp_path / "missing.json")


def test_rejects_unreadable_policy(tmp_path, monkeypatch):
    path = write_policy(tmp_path, valid_policy())
    original_read_text = Path.read_text

    def fail_selected_path(candidate, *args, **kwargs):
        if candidate == path:
            raise OSError("read failed")
        return original_read_text(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_selected_path)

    with pytest.raises(MigrationInventoryError, match="Unable to read migration policy"):
        load_policy(path)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "missing keys"),
        (valid_policy(extra=[]), "unknown keys"),
        ([valid_policy()], "JSON object"),
        (valid_policy(enforced_apps="aap_gateway_api"), "enforced_apps.*array"),
        (valid_policy(enforced_apps=[1]), "enforced_apps.*strings"),
        (valid_policy(allowed_missing={}), "allowed_missing.*array"),
    ],
)
def test_rejects_invalid_policy_shapes(tmp_path, payload, message):
    path = write_policy(tmp_path, payload)

    with pytest.raises(MigrationInventoryError, match=message):
        load_policy(path)


@pytest.mark.parametrize(
    ("field", "values"),
    [
        ("enforced_apps", ["aap_gateway_api", "aap_gateway_api"]),
        ("allowed_missing", ["aap_gateway_api.0001_initial", "aap_gateway_api.0001_initial"]),
        (
            "allowed_fingerprint_changes",
            ["aap_gateway_api.0001_initial", "aap_gateway_api.0001_initial"],
        ),
        ("immutable_vcs_stages", ["published", "published"]),
    ],
)
def test_rejects_duplicate_entries(tmp_path, field, values):
    path = write_policy(tmp_path, valid_policy(**{field: values}))

    with pytest.raises(MigrationInventoryError, match=f"duplicate.*{field}"):
        load_policy(path)


@pytest.mark.parametrize(
    "migration_key",
    [
        "missing_dot",
        "too.many.dots",
        "bad-app.0001_initial",
        "good.bad-name",
        ".0001_initial",
        "app.",
    ],
)
def test_rejects_malformed_migration_keys(tmp_path, migration_key):
    path = write_policy(tmp_path, valid_policy(allowed_missing=[migration_key]))

    with pytest.raises(MigrationInventoryError, match="migration key"):
        load_policy(path)


@pytest.mark.parametrize("field", ["allowed_missing", "allowed_fingerprint_changes"])
def test_rejects_exception_outside_enforced_app(tmp_path, field):
    path = write_policy(tmp_path, valid_policy(**{field: ["dab_rbac.0001_initial"]}))

    with pytest.raises(MigrationInventoryError, match="not enforced"):
        load_policy(path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("enforced_apps", ["bad-app"], "Invalid enforced app label"),
        ("immutable_vcs_stages", ["bad/stage"], "Invalid immutable VCS stage name"),
    ],
)
def test_rejects_invalid_app_labels_and_vcs_stage_names(tmp_path, field, value, message):
    path = write_policy(tmp_path, valid_policy(**{field: value}))

    with pytest.raises(MigrationInventoryError, match=message):
        load_policy(path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("non_object", "inventory must be an object"),
        ("missing", "missing fields"),
        ("unknown", "unknown fields"),
        ("stage", "stage does not match"),
        ("checkout_sha", "checkout SHA does not match"),
    ],
)
def test_validates_inventory_top_level_shape(mutation, message):
    payload = valid_inventory_payload()
    if mutation == "non_object":
        payload = None
    elif mutation == "missing":
        del payload["applied"]
    elif mutation == "unknown":
        payload["unexpected"] = True
    elif mutation == "stage":
        payload["stage"] = "other"
    elif mutation == "checkout_sha":
        payload["checkout_sha"] = "c" * 40

    with pytest.raises(MigrationInventoryError, match=message):
        validate_inventory(payload, expected_stage="release", expected_checkout_sha="b" * 40)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"available": []}, "available must be an object"),
        ({"available": {"bad-key": "a" * 64}}, "invalid migration key"),
        ({"available": {"example_app.0001_initial": "bad"}}, "invalid fingerprint"),
        ({"applied": "example_app.0001_initial"}, "applied must be an array"),
        ({"applied": ["example_app.0001_initial"] * 2}, "duplicate migration keys"),
        ({"applied": ["bad-key"]}, "invalid migration key"),
        ({"dependencies": {}}, "keys must match available"),
        ({"dependencies": {"example_app.0001_initial": "bad"}}, "must be an array"),
        ({"replacements": {}}, "keys must match available"),
        ({"replacements": {"example_app.0001_initial": ["bad-key"]}}, "array of migration keys"),
    ],
)
def test_validates_inventory_migration_graphs(mutation, message):
    payload = valid_inventory_payload()
    payload.update(mutation)

    with pytest.raises(MigrationInventoryError, match=message):
        validate_inventory(payload, expected_stage="release", expected_checkout_sha="b" * 40)


@pytest.mark.parametrize(
    ("vcs_dependencies", "message"),
    [
        ("not-an-array", "vcs_dependencies must be an array"),
        ([None], "VCS dependency must be an object"),
        ([{"distribution": "Example"}], "invalid fields"),
        (
            [{"distribution": "Bad;Name", "vcs": "git", "requested_revision": None, "commit_id": "a" * 40, "editable": False}],
            "invalid distribution name",
        ),
        (
            [{"distribution": "Example", "vcs": "!", "requested_revision": None, "commit_id": "a" * 40, "editable": False}],
            "invalid VCS type",
        ),
        (
            [{"distribution": "Example", "vcs": "git", "requested_revision": None, "commit_id": "bad", "editable": False}],
            "invalid identity fields",
        ),
        (
            [{"distribution": "Example", "vcs": "git", "requested_revision": "bad:revision", "commit_id": "a" * 40, "editable": False}],
            "invalid requested_revision",
        ),
        (
            [{"distribution": "Example", "vcs": "git", "requested_revision": None, "commit_id": "a" * 40, "editable": "false"}],
            "invalid editable flag",
        ),
    ],
)
def test_validates_inventory_vcs_metadata(vcs_dependencies, message):
    payload = valid_inventory_payload()
    payload["vcs_dependencies"] = vcs_dependencies

    with pytest.raises(MigrationInventoryError, match=message):
        validate_inventory(payload, expected_stage="release", expected_checkout_sha="b" * 40)


def migration(module_name, *, dependencies=(), replaces=()):
    migration_class = type("Migration", (), {"__module__": module_name})
    instance = migration_class()
    instance.dependencies = list(dependencies)
    instance.replaces = list(replaces)
    return instance


class FakeDistribution:
    def __init__(self, name, direct_url):
        self.metadata = {"Name": name}
        self.direct_url = direct_url

    def read_text(self, filename):
        assert filename == "direct_url.json"
        return self.direct_url


def install_inventory_fakes(monkeypatch, tmp_path, *, direct_urls=None):
    # build_inventory imports Django lazily inside the function so the host CI
    # runner can start without Django. Patch the Django modules it imports from.
    import django
    from django.db import connection
    from django.db.migrations import loader as migrations_loader
    from django.db.migrations import recorder as migrations_recorder

    first_path = tmp_path / "0001_initial.py"
    first_path.write_bytes(b"first migration\n")
    second_path = tmp_path / "0002_next.py"
    second_path.write_bytes(b"second migration\n")

    migrations = {
        ("example_app", "0002_next"): migration(
            "example_app.migrations.0002_next",
            dependencies=[("example_app", "0001_initial")],
            replaces=[("example_app", "0001_squashed")],
        ),
        ("example_app", "0001_initial"): migration("example_app.migrations.0001_initial"),
    }
    module_paths = {
        "example_app.migrations.0001_initial": first_path,
        "example_app.migrations.0002_next": second_path,
    }

    class FakeLoader:
        def __init__(self, connection_arg):
            assert connection_arg is connection
            self.disk_migrations = migrations

    class FakeRecorder:
        def __init__(self, connection_arg):
            assert connection_arg is connection

        def applied_migrations(self):
            return {("example_app", "0001_initial"): object()}

    monkeypatch.setattr(django, "setup", lambda: None)
    monkeypatch.setattr(migrations_loader, "MigrationLoader", FakeLoader)
    monkeypatch.setattr(migrations_recorder, "MigrationRecorder", FakeRecorder)
    monkeypatch.setattr(
        migration_inventory.importlib,
        "import_module",
        lambda module_name: SimpleNamespace(__file__=str(module_paths[module_name])),
    )
    monkeypatch.setattr(
        migration_inventory.metadata,
        "distributions",
        lambda: list(direct_urls or []),
    )
    return first_path, second_path


def test_build_inventory_is_deterministic_and_redacts_vcs_url(tmp_path, monkeypatch):
    direct_url = json.dumps(
        {
            "url": "https://token@example.invalid/organization/repository.git",
            "vcs_info": {
                "vcs": "git",
                "requested_revision": "release-tag",
                "commit_id": "a" * 40,
            },
            "dir_info": {"editable": True},
        }
    )
    first_path, second_path = install_inventory_fakes(
        monkeypatch,
        tmp_path,
        direct_urls=[FakeDistribution("Example Distribution", direct_url)],
    )

    inventory = build_inventory("release", "b" * 40)

    assert inventory == {
        "stage": "release",
        "checkout_sha": "b" * 40,
        "available": {
            "example_app.0001_initial": sha256(first_path.read_bytes()).hexdigest(),
            "example_app.0002_next": sha256(second_path.read_bytes()).hexdigest(),
        },
        "applied": ["example_app.0001_initial"],
        "dependencies": {
            "example_app.0001_initial": [],
            "example_app.0002_next": ["example_app.0001_initial"],
        },
        "replacements": {
            "example_app.0001_initial": [],
            "example_app.0002_next": ["example_app.0001_squashed"],
        },
        "vcs_dependencies": [
            {
                "distribution": "Example Distribution",
                "vcs": "git",
                "requested_revision": "release-tag",
                "commit_id": "a" * 40,
                "editable": True,
            }
        ],
    }
    assert "token@example.invalid" not in json.dumps(inventory)


@pytest.mark.parametrize(
    ("direct_url", "message"),
    [
        ("{not json", "direct_url.json"),
        (
            json.dumps(
                {
                    "url": "https://example.invalid/repository.git",
                    "vcs_info": {"vcs": "git", "requested_revision": "devel"},
                }
            ),
            "commit_id",
        ),
    ],
)
def test_rejects_invalid_vcs_provenance(tmp_path, monkeypatch, direct_url, message):
    install_inventory_fakes(
        monkeypatch,
        tmp_path,
        direct_urls=[FakeDistribution("Broken Distribution", direct_url)],
    )

    with pytest.raises(MigrationInventoryError, match=message):
        build_inventory("release", "b" * 40)


@pytest.mark.parametrize(
    ("distribution_name", "direct_url", "message"),
    [
        ("Example Distribution", json.dumps([]), "expected an object"),
        ("Example Distribution", json.dumps({"vcs_info": "git"}), "Invalid VCS metadata"),
        ("Example Distribution", json.dumps({"vcs_info": {"vcs": "git", "commit_id": "bad"}}), "commit_id"),
        (
            "Example Distribution",
            json.dumps({"vcs_info": {"vcs": "https://example.invalid", "commit_id": "a" * 40}}),
            "safe VCS type",
        ),
        (
            "Example Distribution",
            json.dumps({"vcs_info": {"vcs": "git", "commit_id": "a" * 40, "requested_revision": "unsafe:ref"}}),
            "unsafe requested_revision",
        ),
        (
            "Example Distribution",
            json.dumps({"vcs_info": {"vcs": "git", "commit_id": "a" * 40}, "dir_info": []}),
            "invalid dir_info",
        ),
        (
            "Example Distribution",
            json.dumps({"vcs_info": {"vcs": "git", "commit_id": "a" * 40}, "dir_info": {"editable": "false"}}),
            "invalid editable flag",
        ),
        (
            "Bad;Distribution",
            json.dumps({"vcs_info": {"vcs": "git", "commit_id": "a" * 40}}),
            "unsafe distribution name",
        ),
    ],
)
def test_rejects_unsafe_vcs_metadata_shapes(tmp_path, monkeypatch, distribution_name, direct_url, message):
    install_inventory_fakes(monkeypatch, tmp_path, direct_urls=[FakeDistribution(distribution_name, direct_url)])

    with pytest.raises(MigrationInventoryError, match=message):
        build_inventory("release", "b" * 40)


@pytest.mark.parametrize(
    ("stage", "checkout_sha", "message"),
    [
        ("bad/stage", "b" * 40, "Invalid stage name"),
        ("release", "bad-sha", "Invalid checkout SHA"),
    ],
)
def test_rejects_invalid_inventory_identifiers(tmp_path, monkeypatch, stage, checkout_sha, message):
    install_inventory_fakes(monkeypatch, tmp_path)

    with pytest.raises(MigrationInventoryError, match=message):
        build_inventory(stage, checkout_sha)


def test_rejects_unsafe_requested_vcs_revision_without_echoing_it(tmp_path, monkeypatch):
    unsafe_revision = "https://example.invalid/private-path"
    install_inventory_fakes(
        monkeypatch,
        tmp_path,
        direct_urls=[
            FakeDistribution(
                "Example Distribution",
                json.dumps(
                    {
                        "url": "https://example.invalid/repository.git",
                        "vcs_info": {"vcs": "git", "requested_revision": unsafe_revision, "commit_id": "a" * 40},
                    }
                ),
            )
        ],
    )

    with pytest.raises(MigrationInventoryError, match="unsafe requested_revision") as error:
        build_inventory("release", "b" * 40)

    assert unsafe_revision not in str(error.value)


def test_ignores_non_vcs_direct_url(tmp_path, monkeypatch):
    install_inventory_fakes(
        monkeypatch,
        tmp_path,
        direct_urls=[
            FakeDistribution(
                "Archive Distribution",
                json.dumps({"url": "https://example.invalid/archive.tar.gz", "archive_info": {}}),
            )
        ],
    )

    inventory = build_inventory("release", "b" * 40)

    assert inventory["vcs_dependencies"] == []


@pytest.mark.parametrize(
    ("requested_revision", "commit_id", "editable", "expected_violation"),
    [
        ("a" * 40, "a" * 40, False, False),
        ("a" * 40, "b" * 40, False, True),
        ("v1.2.3", "b" * 40, False, True),
        ("main", "b" * 40, False, True),
        ("devel", "b" * 40, False, True),
        (None, "b" * 40, False, True),
        ("v1.2.3", None, False, True),
        ("v1.2.3", "b" * 40, True, True),
    ],
)
def test_validates_immutable_stage_vcs_provenance(requested_revision, commit_id, editable, expected_violation):
    policy = MigrationPolicy(
        enforced_apps=frozenset({"aap_gateway_api"}),
        allowed_missing=frozenset(),
        allowed_fingerprint_changes=frozenset(),
        immutable_vcs_stages=frozenset({"published"}),
    )
    dependency = {
        "distribution": "Example Distribution",
        "vcs": "git",
        "requested_revision": requested_revision,
        "commit_id": commit_id,
        "editable": editable,
    }

    violations = validate_vcs_provenance({"stage": "published", "vcs_dependencies": [dependency]}, policy)

    assert bool(violations) is expected_violation


def test_immutable_stage_requires_requested_revision_to_be_a_full_commit_sha():
    policy = MigrationPolicy(
        enforced_apps=frozenset({"aap_gateway_api"}),
        allowed_missing=frozenset(),
        allowed_fingerprint_changes=frozenset(),
        immutable_vcs_stages=frozenset({"published"}),
    )
    dependency = {
        "distribution": "Example Distribution",
        "vcs": "git",
        "requested_revision": "v1.2.3",
        "commit_id": "b" * 40,
        "editable": False,
    }

    violations = validate_vcs_provenance({"stage": "published", "vcs_dependencies": [dependency]}, policy)

    assert len(violations) == 1
    assert violations[0].reason == "requested revision must be a full Git SHA"


def test_skips_vcs_provenance_enforcement_for_unlisted_stage():
    policy = MigrationPolicy(
        enforced_apps=frozenset({"aap_gateway_api"}),
        allowed_missing=frozenset(),
        allowed_fingerprint_changes=frozenset(),
        immutable_vcs_stages=frozenset({"published"}),
    )

    violations = validate_vcs_provenance(
        {
            "stage": "pull-request",
            "vcs_dependencies": [
                {
                    "distribution": "Example Distribution",
                    "vcs": "git",
                    "requested_revision": "devel",
                    "commit_id": "b" * 40,
                    "editable": True,
                }
            ],
        },
        policy,
    )

    assert violations == []


def test_reports_every_unpinned_vcs_distribution():
    policy = MigrationPolicy(
        enforced_apps=frozenset({"aap_gateway_api"}),
        allowed_missing=frozenset(),
        allowed_fingerprint_changes=frozenset(),
        immutable_vcs_stages=frozenset({"published"}),
    )
    dependencies = [
        {
            "distribution": name,
            "vcs": "git",
            "requested_revision": "devel",
            "commit_id": "b" * 40,
            "editable": False,
        }
        for name in ("First Distribution", "Second Distribution")
    ]

    violations = validate_vcs_provenance({"stage": "published", "vcs_dependencies": dependencies}, policy)

    assert [violation.distribution for violation in violations] == ["First Distribution", "Second Distribution"]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"stage": None, "vcs_dependencies": []}, "stage must be a string"),
        ({"stage": "published"}, "vcs_dependencies must be an array"),
        ({"stage": "published", "vcs_dependencies": [None]}, "VCS dependency must be an object"),
    ],
)
def test_vcs_provenance_validation_rejects_malformed_inputs(payload, message):
    policy = MigrationPolicy(
        enforced_apps=frozenset({"aap_gateway_api"}),
        allowed_missing=frozenset(),
        allowed_fingerprint_changes=frozenset(),
        immutable_vcs_stages=frozenset({"published"}),
    )

    with pytest.raises(MigrationInventoryError, match=message):
        validate_vcs_provenance(payload, policy)


def test_vcs_provenance_validation_rejects_non_git_dependencies():
    policy = MigrationPolicy(
        enforced_apps=frozenset({"aap_gateway_api"}),
        allowed_missing=frozenset(),
        allowed_fingerprint_changes=frozenset(),
        immutable_vcs_stages=frozenset({"published"}),
    )
    dependency = {
        "distribution": "Example Distribution",
        "vcs": "hg",
        "requested_revision": "v1.2.3",
        "commit_id": "a" * 40,
        "editable": False,
    }

    violations = validate_vcs_provenance({"stage": "published", "vcs_dependencies": [dependency]}, policy)

    assert violations[0].reason == "only Git dependencies are supported for immutable-stage validation"


def test_rejects_migration_without_source_file(tmp_path, monkeypatch):
    install_inventory_fakes(monkeypatch, tmp_path)
    monkeypatch.setattr(
        migration_inventory.importlib,
        "import_module",
        lambda module_name: SimpleNamespace(__file__=None),
    )

    with pytest.raises(MigrationInventoryError, match="source file"):
        build_inventory("release", "b" * 40)


def test_rejects_missing_migration_source_file(tmp_path, monkeypatch):
    install_inventory_fakes(monkeypatch, tmp_path)
    missing = tmp_path / "missing.py"
    monkeypatch.setattr(
        migration_inventory.importlib,
        "import_module",
        lambda module_name: SimpleNamespace(__file__=str(missing)),
    )

    with pytest.raises(MigrationInventoryError, match="does not exist"):
        build_inventory("release", "b" * 40)


def test_resolves_bytecode_migration_to_python_source(tmp_path, monkeypatch):
    source_path = tmp_path / "0001_initial.py"
    bytecode_path = source_path.with_suffix(".pyc")
    source_path.write_text("# migration source\n", encoding="utf-8")
    monkeypatch.setattr(migration_inventory.importlib, "import_module", lambda module_name: SimpleNamespace(__file__=str(bytecode_path)))

    resolved_path = migration_inventory._migration_source_path("example_app.0001_initial", migration("example_app.migrations.0001_initial"))

    assert resolved_path == source_path


def test_rejects_migration_with_non_python_source(tmp_path, monkeypatch):
    source_path = tmp_path / "0001_initial.txt"
    source_path.write_text("not Python", encoding="utf-8")
    monkeypatch.setattr(migration_inventory.importlib, "import_module", lambda module_name: SimpleNamespace(__file__=str(source_path)))
    migration_instance = migration("example_app.migrations.0001_initial")

    with pytest.raises(MigrationInventoryError, match="not Python source"):
        migration_inventory._migration_source_path("example_app.0001_initial", migration_instance)


def test_write_inventory_creates_parent_and_atomically_replaces_file(tmp_path):
    output = tmp_path / "nested" / "inventory.json"
    output.parent.mkdir()
    output.write_text("old content", encoding="utf-8")

    write_inventory(output, {"stage": "release", "applied": []})

    assert json.loads(output.read_text(encoding="utf-8")) == {
        "applied": [],
        "stage": "release",
    }
    assert list(output.parent.glob("*.tmp")) == []


def test_write_inventory_creates_missing_parent(tmp_path):
    output = tmp_path / "missing" / "inventory.json"

    write_inventory(output, {"stage": "release"})

    assert json.loads(output.read_text(encoding="utf-8")) == {"stage": "release"}


def test_write_inventory_cleans_temporary_file_after_replace_error(tmp_path, monkeypatch):
    output = tmp_path / "inventory.json"

    monkeypatch.setattr(Path, "replace", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("replace failed")))
    with pytest.raises(OSError, match="replace failed"):
        write_inventory(output, {"stage": "release"})

    assert list(tmp_path.iterdir()) == []


def test_inventory_cli_writes_collected_inventory(tmp_path, monkeypatch, capsys):
    payload = valid_inventory_payload()
    monkeypatch.setattr(migration_inventory, "build_inventory", lambda stage, sha: payload)
    output = tmp_path / "nested" / "inventory.json"

    result = migration_inventory.main(["--stage", "release", "--checkout-sha", "b" * 40, "--output", str(output)])

    assert result == 0
    assert json.loads(output.read_text(encoding="utf-8")) == payload
    assert "available=1" in capsys.readouterr().out
