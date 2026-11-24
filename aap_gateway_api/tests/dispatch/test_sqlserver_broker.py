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


@pytest.mark.skipif(connection.vendor != "microsoft", reason="SQL Server Service Broker round-trip only")
@pytest.mark.django_db(transaction=True)
def test_sqlserver_publish_through_gateway_factory_is_transactional():
    """The configured publisher factory returns Django's connection: publish-on-commit, rollback-retracts."""
    from django.db import transaction

    from aap_gateway_api.dispatch.config import get_dispatcherd_config, pyodbc_connection_from_config

    config = get_dispatcherd_config()["brokers"]["sqlserver"]["config"]
    channel = f"txn_{uuid.uuid4().hex}"

    listener = Broker(config, channels=[channel], wait_timeout_ms=100)
    listener.register()
    try:
        # A short-lived broker borrowing Django's live connection, exactly as
        # dispatcherd's documented Django publishing pattern prescribes.
        publisher = Broker(config, sync_connection=pyodbc_connection_from_config())
        try:
            with transaction.atomic():
                publisher.broadcast(channel, json.dumps({"txn": "commit"}))
                # The listener is on its own connection: the uncommitted
                # queue row must not be visible to it.
                assert listener._receive(300) is None
        finally:
            publisher.close()  # does not close Django's connection
        received = listener._receive(15000)
        assert received == (channel, json.dumps({"txn": "commit"}))

        rollback_publisher = Broker(config, sync_connection=pyodbc_connection_from_config())
        try:
            with transaction.atomic():
                rollback_publisher.broadcast(channel, json.dumps({"txn": "rollback"}))
                raise RuntimeError("force rollback")
        except RuntimeError:
            pass
        finally:
            rollback_publisher.close()
        # Nothing from the rolled-back transaction may arrive.
        assert listener._receive(300) is None
    finally:
        listener.close()
