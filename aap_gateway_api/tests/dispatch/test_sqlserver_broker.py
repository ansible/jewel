"""Live round-trip through dispatcherd's SQL Server Service Broker.

Runs against a provisioned SQL Server test database; skipped on PostgreSQL.
Uses Gateway's generated connection settings to publish and receive a message
on a test channel. Does not exercise Gateway's publisher factory or a running
dispatcherd service.
"""

import json
import uuid

import pytest
from django.db import connection

pytest.importorskip("pyodbc", exc_type=ImportError)
pytest.importorskip("aioodbc")
from dispatcherd.brokers.sqlserver import Broker  # noqa: E402 — import after optional dependency checks


@pytest.mark.skipif(connection.vendor != "microsoft", reason="SQL Server Service Broker round-trip only")
@pytest.mark.django_db
def test_sqlserver_broker_round_trip():
    from aap_gateway_api.dispatch.config import get_dispatcherd_config

    config = get_dispatcherd_config()["brokers"]["sqlserver"]["config"]
    channel = f"smoke_{uuid.uuid4().hex}"

    listener = Broker(config, channels=[channel], wait_timeout_ms=100)
    publisher = Broker(config)
    try:
        listener.register()
        payload = json.dumps({"smoke": True})
        assert len(publisher.broadcast(channel, payload)) == 1
        received = listener._receive(15000)
        assert received == (channel, payload)
        assert listener._receive(200) is None
    finally:
        listener.close()
        publisher.close()
