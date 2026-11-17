import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_setup_service_broker_noop_on_postgres(capsys):
    """On PostgreSQL the command logs and does nothing (vendor guard)."""
    call_command("setup_service_broker")
    assert "not required" in capsys.readouterr().out
