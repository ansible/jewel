import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[3] / "tools" / "scripts" / "ci"))
import migration_snapshot_fixture as snapshot_fixture  # noqa: E402


class FakeQuerySet(list):
    def order_by(self, field):
        assert field == "pk"
        return self


class FakeOrganization:
    def __init__(self, pk, name, managed=False):
        self.pk = pk
        self.name = name
        self.managed = managed


class FakeTeam:
    def __init__(self, pk, name, organization):
        self.pk = pk
        self.name = name
        self.organization = organization
        self.saved_fields = []

    @property
    def organization_id(self):
        return self.organization.pk

    def save(self, *, update_fields):
        self.saved_fields = update_fields


class FakeOrganizationManager:
    def __init__(self, organizations=None):
        self.organizations = list(organizations or [])
        self.get_or_create_calls = []

    def get_or_create(self, *, name, defaults):
        self.get_or_create_calls.append({"name": name, "defaults": defaults})
        matches = [organization for organization in self.organizations if organization.name == name]
        if matches:
            return matches[0], False
        organization = FakeOrganization(len(self.organizations) + 1, name, defaults["managed"])
        self.organizations.append(organization)
        return organization, True

    def filter(self, *, name):
        return FakeQuerySet([organization for organization in self.organizations if organization.name == name])


class FakeTeamManager:
    def __init__(self, teams=None):
        self.teams = list(teams or [])
        self.get_or_create_calls = []

    def get_or_create(self, *, name, organization):
        self.get_or_create_calls.append({"name": name, "organization": organization})
        matches = [team for team in self.teams if team.name == name and team.organization_id == organization.pk]
        if matches:
            return matches[0], False
        team = FakeTeam(len(self.teams) + 1, name, organization)
        self.teams.append(team)
        return team, True

    def filter(self, *, name):
        return FakeQuerySet([team for team in self.teams if team.name == name])


class FakeCursor:
    def __init__(self, counts):
        self.counts = counts
        self.queries = []
        self.table = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query):
        self.queries.append(query)
        self.table = query.split('"')[1]

    def fetchone(self):
        return (self.counts[self.table],)


class FakeConnection:
    def __init__(self, counts):
        self._cursor = FakeCursor(counts)
        self.introspection = SimpleNamespace(table_names=lambda: list(counts))
        self.ops = SimpleNamespace(quote_name=lambda name: f'"{name}"')

    def cursor(self):
        return self._cursor


def install_models(monkeypatch, *, organizations=None, teams=None):
    organization_manager = FakeOrganizationManager(organizations)
    team_manager = FakeTeamManager(teams)
    organization_model = SimpleNamespace(objects=organization_manager)
    team_model = SimpleNamespace(objects=team_manager)
    models = {
        ("aap_gateway_api", "Organization"): organization_model,
        ("aap_gateway_api", "Team"): team_model,
    }
    monkeypatch.setattr(snapshot_fixture.django, "setup", lambda: None)
    monkeypatch.setattr(snapshot_fixture.apps, "get_model", lambda app, model: models[(app, model)])
    monkeypatch.setattr(
        snapshot_fixture,
        "settings",
        SimpleNamespace(
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.postgresql",
                    "NAME": "gw_db",
                    "HOST": "127.0.0.1",
                    "PORT": "5432",
                    "OPTIONS": {},
                }
            }
        ),
    )
    monkeypatch.setenv("DATABASE_NAME", "gw_db")
    monkeypatch.setenv("DATABASE_PORT", "5432")
    return organization_manager, team_manager


@pytest.mark.parametrize(
    "database",
    [
        {"ENGINE": "django.db.backends.postgresql", "NAME": "gw_db", "HOST": "127.0.0.1", "PORT": "5432", "OPTIONS": {}},
        {"ENGINE": "django.db.backends.postgresql", "NAME": "gw_db", "HOST": "localhost", "PORT": 5432, "OPTIONS": {}},
        {"ENGINE": "django.db.backends.postgresql", "NAME": "gw_db", "HOST": "", "PORT": "5432", "OPTIONS": {}},
    ],
)
def test_validate_effective_database_accepts_local_postgres(monkeypatch, database):
    monkeypatch.setattr(snapshot_fixture.django, "setup", lambda: None)
    monkeypatch.setattr(snapshot_fixture, "settings", SimpleNamespace(DATABASES={"default": database}))
    monkeypatch.setenv("DATABASE_NAME", "gw_db")
    monkeypatch.setenv("DATABASE_PORT", "5432")

    snapshot_fixture.validate_effective_database()


@pytest.mark.parametrize(
    "database",
    [
        {"ENGINE": "django.db.backends.postgresql", "NAME": "gw_db", "HOST": "db.example.invalid", "PORT": "5432", "OPTIONS": {}},
        {"ENGINE": "django.db.backends.postgresql", "NAME": "gw_db", "HOST": "127.0.0.1", "PORT": "5432", "OPTIONS": {"hostaddr": "198.51.100.10"}},
        {"ENGINE": "django.db.backends.postgresql", "NAME": "gw_db", "HOST": "127.0.0.1", "PORT": "5432", "OPTIONS": {"service": "remote"}},
        {"ENGINE": "django.db.backends.postgresql", "NAME": "other_db", "HOST": "127.0.0.1", "PORT": "5432", "OPTIONS": {}},
        {"ENGINE": "django.db.backends.sqlite3", "NAME": "gw_db", "HOST": "", "PORT": "5432", "OPTIONS": {}},
        {"ENGINE": "django.db.backends.postgresql", "NAME": "gw_db", "HOST": "127.0.0.1", "PORT": "6543", "OPTIONS": {}},
        {"ENGINE": "django.db.backends.postgresql", "NAME": "gw_db", "HOST": "127.0.0.1", "PORT": "5432", "OPTIONS": {"port": "6543"}},
    ],
)
def test_validate_effective_database_rejects_nonlocal_or_overridden_connections(monkeypatch, database):
    monkeypatch.setattr(snapshot_fixture.django, "setup", lambda: None)
    monkeypatch.setattr(snapshot_fixture, "settings", SimpleNamespace(DATABASES={"default": database}))
    monkeypatch.setenv("DATABASE_NAME", "gw_db")
    monkeypatch.setenv("DATABASE_PORT", "5432")

    with pytest.raises(snapshot_fixture.MigrationSnapshotFixtureError, match="local PostgreSQL database"):
        snapshot_fixture.validate_effective_database()


def test_validate_effective_database_does_not_expose_connection_details(monkeypatch):
    monkeypatch.setattr(snapshot_fixture.django, "setup", lambda: None)
    monkeypatch.setattr(
        snapshot_fixture,
        "settings",
        SimpleNamespace(
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.postgresql",
                    "NAME": "gw_db",
                    "HOST": "secret-host.example.invalid",
                    "PORT": "5432",
                    "PASSWORD": "sensitive-password",
                    "OPTIONS": {"service": "secret-service"},
                }
            }
        ),
    )
    monkeypatch.setenv("DATABASE_NAME", "gw_db")
    monkeypatch.setenv("DATABASE_PORT", "5432")

    with pytest.raises(snapshot_fixture.MigrationSnapshotFixtureError) as error:
        snapshot_fixture.validate_effective_database()

    assert "secret-host" not in str(error.value)
    assert "sensitive-password" not in str(error.value)
    assert "secret-service" not in str(error.value)


def test_seed_uses_fixed_names_and_get_or_create(monkeypatch):
    organization_manager, team_manager = install_models(monkeypatch)

    snapshot = snapshot_fixture.seed_snapshot_fixture()

    assert organization_manager.get_or_create_calls == [
        {
            "name": "Migration CI Snapshot Organization",
            "defaults": {"managed": False},
        }
    ]
    assert len(team_manager.get_or_create_calls) == 1
    assert team_manager.get_or_create_calls[0]["name"] == "Migration CI Snapshot Team"
    assert team_manager.get_or_create_calls[0]["organization"].name == "Migration CI Snapshot Organization"
    assert snapshot["organization"]["name"] == "Migration CI Snapshot Organization"
    assert snapshot["team"]["name"] == "Migration CI Snapshot Team"


def test_seed_corrects_existing_team_organization(monkeypatch):
    wrong_organization = FakeOrganization(9, "Unrelated Organization")
    existing_team = FakeTeam(4, "Migration CI Snapshot Team", wrong_organization)
    _, team_manager = install_models(monkeypatch, teams=[existing_team])

    snapshot = snapshot_fixture.seed_snapshot_fixture()

    assert existing_team.organization.name == "Migration CI Snapshot Organization"
    assert existing_team.saved_fields == ["organization"]
    assert team_manager.get_or_create_calls == []
    assert snapshot["team"]["organization_id"] == snapshot["organization"]["id"]


def test_seed_is_idempotent(monkeypatch):
    organization_manager, team_manager = install_models(monkeypatch)

    first = snapshot_fixture.seed_snapshot_fixture()
    second = snapshot_fixture.seed_snapshot_fixture()

    assert first == second
    assert len(organization_manager.organizations) == 1
    assert len(team_manager.teams) == 1


def test_model_loading_errors_are_sanitized(monkeypatch):
    monkeypatch.setattr(snapshot_fixture.django, "setup", lambda: (_ for _ in ()).throw(RuntimeError("connection details")))

    with pytest.raises(snapshot_fixture.MigrationSnapshotFixtureError, match="Unable to load") as error:
        snapshot_fixture._models()

    assert "connection details" not in str(error.value)


def test_model_loading_rejects_unavailable_models(monkeypatch):
    install_models(monkeypatch)
    monkeypatch.setattr(snapshot_fixture.django, "setup", lambda: None)
    monkeypatch.setattr(snapshot_fixture.apps, "get_model", lambda app, model: None)

    with pytest.raises(snapshot_fixture.MigrationSnapshotFixtureError, match="models are unavailable"):
        snapshot_fixture._models()


def test_seed_rejects_duplicate_organizations(monkeypatch):
    name = "Migration CI Snapshot Organization"
    organizations = [FakeOrganization(1, name), FakeOrganization(2, name)]
    install_models(monkeypatch, organizations=organizations)

    with pytest.raises(snapshot_fixture.MigrationSnapshotFixtureError, match="exactly one organization"):
        snapshot_fixture.seed_snapshot_fixture()


def test_seed_rejects_duplicate_teams(monkeypatch):
    organization = FakeOrganization(1, "Migration CI Snapshot Organization")
    teams = [
        FakeTeam(1, "Migration CI Snapshot Team", organization),
        FakeTeam(2, "Migration CI Snapshot Team", organization),
    ]
    install_models(monkeypatch, organizations=[organization], teams=teams)

    with pytest.raises(snapshot_fixture.MigrationSnapshotFixtureError, match="at most one team"):
        snapshot_fixture.seed_snapshot_fixture()


def test_seed_wraps_database_errors_without_details(monkeypatch):
    organization_manager, _ = install_models(monkeypatch)
    monkeypatch.setattr(
        organization_manager,
        "get_or_create",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("database credentials")),
    )

    with pytest.raises(snapshot_fixture.MigrationSnapshotFixtureError, match="Unable to seed") as error:
        snapshot_fixture.seed_snapshot_fixture()

    assert "database credentials" not in str(error.value)


def test_snapshot_wraps_database_errors_without_details(monkeypatch):
    organization_manager, _ = install_models(monkeypatch)
    monkeypatch.setattr(
        organization_manager,
        "filter",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("database credentials")),
    )

    with pytest.raises(snapshot_fixture.MigrationSnapshotFixtureError, match="Unable to inspect") as error:
        snapshot_fixture.snapshot_fixture()

    assert "database credentials" not in str(error.value)


def test_snapshot_has_only_fixed_identity_fields_and_writes_deterministic_json(tmp_path, monkeypatch):
    organization = FakeOrganization(42, "Migration CI Snapshot Organization")
    team = FakeTeam(17, "Migration CI Snapshot Team", organization)
    install_models(monkeypatch, organizations=[organization], teams=[team])
    expected = {
        "organization": {"id": "42", "name": "Migration CI Snapshot Organization"},
        "team": {
            "id": "17",
            "name": "Migration CI Snapshot Team",
            "organization_id": "42",
        },
    }

    snapshot = snapshot_fixture.snapshot_fixture()
    first_output = tmp_path / "first.json"
    second_output = tmp_path / "nested" / "second.json"
    snapshot_fixture.write_snapshot(first_output, snapshot)
    snapshot_fixture.write_snapshot(second_output, snapshot)

    assert snapshot == expected
    assert json.loads(first_output.read_text(encoding="utf-8")) == expected
    assert first_output.read_bytes() == second_output.read_bytes()
    assert list(tmp_path.rglob("*.tmp")) == []


def test_database_state_records_counts_migration_keys_and_fixed_fixture(monkeypatch):
    organization = FakeOrganization(42, "Migration CI Snapshot Organization")
    team = FakeTeam(17, "Migration CI Snapshot Team", organization)
    install_models(monkeypatch, organizations=[organization], teams=[team])
    fake_connection = FakeConnection({"aap_gateway_api_team": 1, "aap_gateway_api_organization": 2})
    monkeypatch.setattr(snapshot_fixture, "connection", fake_connection)
    monkeypatch.setattr(
        snapshot_fixture,
        "MigrationRecorder",
        lambda connection: SimpleNamespace(applied_migrations=lambda: {("aap_gateway_api", "0002_team"), ("aap_gateway_api", "0001_initial")}),
    )

    state = snapshot_fixture.database_state_snapshot()

    assert state == {
        "table_counts": {"aap_gateway_api_organization": 2, "aap_gateway_api_team": 1},
        "applied_migrations": ["aap_gateway_api.0001_initial", "aap_gateway_api.0002_team"],
        "fixture": {
            "organization": {"id": "42", "name": "Migration CI Snapshot Organization"},
            "team": {"id": "17", "name": "Migration CI Snapshot Team", "organization_id": "42"},
        },
    }
    assert fake_connection._cursor.queries == [
        'SELECT COUNT(*) FROM "aap_gateway_api_organization"',
        'SELECT COUNT(*) FROM "aap_gateway_api_team"',
    ]


def test_database_state_wraps_connection_errors_without_details(monkeypatch):
    organization = FakeOrganization(42, "Migration CI Snapshot Organization")
    team = FakeTeam(17, "Migration CI Snapshot Team", organization)
    install_models(monkeypatch, organizations=[organization], teams=[team])
    monkeypatch.setattr(snapshot_fixture, "connection", SimpleNamespace(cursor=lambda: (_ for _ in ()).throw(RuntimeError("database credentials"))))

    with pytest.raises(snapshot_fixture.MigrationSnapshotFixtureError, match="Unable to capture") as error:
        snapshot_fixture.database_state_snapshot()

    assert "database credentials" not in str(error.value)


def test_write_snapshot_cleans_temporary_file_after_serialization_failure(tmp_path):
    output = tmp_path / "snapshot.json"

    with pytest.raises(TypeError):
        snapshot_fixture.write_snapshot(output, {"unsupported": object()})

    assert not output.exists()
    assert list(tmp_path.iterdir()) == []


def test_cli_seed_action_prints_only_synthetic_status(monkeypatch, capsys):
    monkeypatch.setattr(snapshot_fixture, "seed_snapshot_fixture", lambda: {})

    assert snapshot_fixture.main(["seed"]) == 0

    assert capsys.readouterr().out == "Seeded fixed synthetic migration snapshot fixtures\n"


def test_cli_validate_connection_prints_only_safe_status(monkeypatch, capsys):
    monkeypatch.setattr(snapshot_fixture, "validate_effective_database", lambda: None)

    assert snapshot_fixture.main(["validate-connection"]) == 0

    assert capsys.readouterr().out == "Validated local PostgreSQL migration database configuration\n"


@pytest.mark.parametrize("action", ["snapshot", "state"])
def test_cli_snapshot_actions_write_only_fixed_json(tmp_path, monkeypatch, capsys, action):
    identity = {
        "organization": {"id": "42", "name": "Migration CI Snapshot Organization"},
        "team": {"id": "17", "name": "Migration CI Snapshot Team", "organization_id": "42"},
    }
    state = {"table_counts": {"aap_gateway_api_team": 1}, "applied_migrations": [], "fixture": identity}
    monkeypatch.setattr(snapshot_fixture, "snapshot_fixture", lambda: identity)
    monkeypatch.setattr(snapshot_fixture, "database_state_snapshot", lambda: state)
    output = tmp_path / f"{action}.json"

    assert snapshot_fixture.main([action, "--output", str(output)]) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == (identity if action == "snapshot" else state)
    assert "database credentials" not in capsys.readouterr().out


def test_cli_converts_fixture_errors_to_argument_errors(monkeypatch, capsys):
    monkeypatch.setattr(
        snapshot_fixture,
        "seed_snapshot_fixture",
        lambda: (_ for _ in ()).throw(snapshot_fixture.MigrationSnapshotFixtureError("fixed fixture is missing")),
    )

    with pytest.raises(SystemExit):
        snapshot_fixture.main(["seed"])

    assert "fixed fixture is missing" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("organizations", "teams", "message"),
    [
        ([], [], "exactly one organization"),
        ([FakeOrganization(1, "Migration CI Snapshot Organization")], [], "exactly one team"),
        (
            [FakeOrganization(1, "Migration CI Snapshot Organization")],
            [
                FakeTeam(1, "Migration CI Snapshot Team", FakeOrganization(1, "Migration CI Snapshot Organization")),
                FakeTeam(2, "Migration CI Snapshot Team", FakeOrganization(1, "Migration CI Snapshot Organization")),
            ],
            "exactly one team",
        ),
        (
            [FakeOrganization(1, "Migration CI Snapshot Organization")],
            [FakeTeam(1, "Migration CI Snapshot Team", FakeOrganization(2, "Different Organization"))],
            "does not belong",
        ),
    ],
)
def test_snapshot_requires_exact_expected_relationship(organizations, teams, message, monkeypatch):
    install_models(monkeypatch, organizations=organizations, teams=teams)

    with pytest.raises(snapshot_fixture.MigrationSnapshotFixtureError, match=message):
        snapshot_fixture.snapshot_fixture()
