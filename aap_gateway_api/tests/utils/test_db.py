import time
from unittest import mock

import pytest
from django.db.utils import OperationalError

import aap_gateway_api.utils.db as db


@pytest.mark.django_db
def test_db_connection():
    result = db.get_db_connection_status('default', 1)
    assert result


def test_db_connection_exception():
    with mock.patch("aap_gateway_api.utils.db._check_db") as mocked_check_db:
        mocked_check_db.side_effect = OperationalError
        with pytest.raises(OperationalError):
            db.get_db_connection_status('default', 1)


@pytest.mark.django_db
def test_check_db():
    assert db._check_db('default')
    with pytest.raises(Exception):
        db._check_db('doesntexist')


def mocked_get_item_raising_exception(key):
    raise OperationalError()


def test_check_db_exception():
    with mock.patch("aap_gateway_api.utils.db.connections") as mocked_connections:
        mocked_connections.__getitem__.side_effect = mocked_get_item_raising_exception
        with pytest.raises(OperationalError):
            db._check_db('default')


# mocked db connection returning mocked cursor
class MockedConnection:
    def cursor(self):
        return MockedCursor()


# mocked cursor sleeping when executing a query
class MockedCursor:
    def execute(self, query):
        time.sleep(3)

    def close(self):
        pass


def test_db_connection_timeout():
    with mock.patch("aap_gateway_api.utils.db.connections") as mocked_connections:
        mocked_connections.__getitem__.return_value = MockedConnection()
        with pytest.raises(TimeoutError):
            db.get_db_connection_status('default', 1)
