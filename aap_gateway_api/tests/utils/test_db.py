import time
from multiprocessing.context import TimeoutError
from unittest import mock

import pytest
from django.db import DatabaseError

from aap_gateway_api.utils.db import _try_connection, get_db_connection_status


@pytest.mark.django_db
def test_db_connection():
    result = get_db_connection_status('default', 1)
    assert result


def test_db_connection_exception():
    with mock.patch("django.db.connections.create_connection", side_effect=DatabaseError("DB no worky")):
        with pytest.raises(DatabaseError):
            get_db_connection_status('default', 1)


@pytest.mark.django_db
def test_try_connection():
    assert _try_connection('default')

    with pytest.raises(Exception):
        _try_connection('doesntexist')


def test_try_connection_exception():
    with mock.patch("django.db.connections.create_connection", side_effect=DatabaseError("DB no worky")):
        with pytest.raises(DatabaseError):
            _try_connection('default')


def _sleeper(dbname):
    time.sleep(10)


def test_db_connection_timeout():
    with mock.patch("django.db.connections.create_connection", side_effect=_sleeper):
        with pytest.raises(TimeoutError):
            get_db_connection_status('default', 1)
