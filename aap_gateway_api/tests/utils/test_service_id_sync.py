import time
import uuid
from unittest import mock

import pytest

from aap_gateway_api.models import ServiceCluster
from aap_gateway_api.utils.service_id_sync import (
    _POPULATE_MAX_COOLDOWN_ENTRIES,
    _check_and_set_cooldown,
    _fetch_service_id_for_route,
    _populate_cooldown,
    populate_service_id,
)

MOCK_TARGET = "aap_gateway_api.utils.service_id_sync._fetch_service_id_for_route"


# ---------------------------------------------------------------------------
# _fetch_service_id_for_route
# ---------------------------------------------------------------------------


def test_fetch_returns_none_on_non_200(service_api_route_controller):
    """Returns None when the metadata endpoint returns a non-200 status."""
    resp = mock.Mock()
    resp.status_code = 500

    with mock.patch("aap_gateway_api.utils.service_id_sync.resources_client.GWResourceAPIClient") as mock_cls:
        mock_cls.return_value.get_service_metadata.return_value = resp
        result = _fetch_service_id_for_route(service_api_route_controller)

    assert result is None


def test_fetch_returns_none_on_exception(service_api_route_controller):
    """Returns None when the HTTP call raises an exception."""
    with mock.patch("aap_gateway_api.utils.service_id_sync.resources_client.GWResourceAPIClient") as mock_cls:
        mock_cls.return_value.get_service_metadata.side_effect = ConnectionError("boom")
        result = _fetch_service_id_for_route(service_api_route_controller)

    assert result is None


def test_fetch_returns_canonical_uuid(service_api_route_controller):
    """Returns a canonical lowercase UUID string from a successful metadata response."""
    raw = str(uuid.uuid4()).upper()
    resp = mock.Mock()
    resp.status_code = 200
    resp.json.return_value = {"service_id": raw}

    with mock.patch("aap_gateway_api.utils.service_id_sync.resources_client.GWResourceAPIClient") as mock_cls:
        mock_cls.return_value.get_service_metadata.return_value = resp
        result = _fetch_service_id_for_route(service_api_route_controller)

    assert result == raw.lower()


def test_fetch_returns_none_for_invalid_uuid(service_api_route_controller):
    """Returns None when the metadata endpoint returns a non-UUID service_id."""
    resp = mock.Mock()
    resp.status_code = 200
    resp.json.return_value = {"service_id": "not-a-uuid"}

    with mock.patch("aap_gateway_api.utils.service_id_sync.resources_client.GWResourceAPIClient") as mock_cls:
        mock_cls.return_value.get_service_metadata.return_value = resp
        result = _fetch_service_id_for_route(service_api_route_controller)

    assert result is None


# ---------------------------------------------------------------------------
# _check_and_set_cooldown
# ---------------------------------------------------------------------------


def test_cooldown_hit_returns_true():
    """Second call with the same issuer within the window returns True (on cooldown)."""
    issuer = str(uuid.uuid4())
    _populate_cooldown.pop(issuer, None)
    try:
        assert _check_and_set_cooldown(issuer) is False
        assert _check_and_set_cooldown(issuer) is True
    finally:
        _populate_cooldown.pop(issuer, None)


def test_cooldown_pruning_removes_expired_entries():
    """When the dict is at cap with expired entries, they are pruned and the new issuer is admitted."""
    issuer = str(uuid.uuid4())
    original = dict(_populate_cooldown)
    try:
        far_past = time.monotonic() - 120
        for i in range(_POPULATE_MAX_COOLDOWN_ENTRIES):
            _populate_cooldown[f"expired-{i}"] = far_past

        result = _check_and_set_cooldown(issuer)

        assert result is False  # admitted after pruning
        assert all(not k.startswith("expired-") for k in _populate_cooldown)
    finally:
        _populate_cooldown.clear()
        _populate_cooldown.update(original)


def test_cooldown_full_of_fresh_entries_blocks_new_issuer():
    """When the dict is at cap with fresh entries and pruning frees nothing, the issuer is blocked."""
    issuer = str(uuid.uuid4())
    original = dict(_populate_cooldown)
    try:
        fresh = time.monotonic()
        for i in range(_POPULATE_MAX_COOLDOWN_ENTRIES):
            _populate_cooldown[f"fresh-{i}"] = fresh

        result = _check_and_set_cooldown(issuer)

        assert result is True  # blocked — dict still full after pruning attempt
        assert issuer not in _populate_cooldown
    finally:
        _populate_cooldown.clear()
        _populate_cooldown.update(original)


# ---------------------------------------------------------------------------
# populate_service_id
# ---------------------------------------------------------------------------


def test_populate_returns_none_for_non_uuid():
    """Returns None immediately when the iss claim is not a valid UUID."""
    result = populate_service_id("not-a-uuid")
    assert result is None


@pytest.mark.django_db
def test_populate_returns_none_when_on_cooldown(service_cluster_controller, service_api_route_controller):
    """Returns None without probing when the issuer is on cooldown."""
    service_cluster_controller.service_id = None
    service_cluster_controller.save()

    target_id = str(uuid.uuid4())
    _populate_cooldown.pop(target_id, None)
    try:
        with mock.patch(MOCK_TARGET, return_value=str(uuid.uuid4())):
            populate_service_id(target_id)  # sets cooldown

        with mock.patch(MOCK_TARGET) as mock_fetch:
            result = populate_service_id(target_id)
            mock_fetch.assert_not_called()

        assert result is None
    finally:
        _populate_cooldown.pop(target_id, None)


@pytest.mark.django_db
def test_populate_returns_none_when_no_null_clusters(service_cluster_controller, service_api_route_controller):
    """Returns None when all clusters already have a service_id."""
    service_cluster_controller.service_id = uuid.uuid4()
    service_cluster_controller.save()

    result = populate_service_id(str(uuid.uuid4()))
    assert result is None


@pytest.mark.django_db
def test_populate_returns_none_when_no_route(service_cluster_controller):
    """Returns None when the null-id cluster has no ServiceAPIRoute."""
    service_cluster_controller.service_id = None
    service_cluster_controller.save()

    result = populate_service_id(str(uuid.uuid4()))
    assert result is None


@pytest.mark.django_db
def test_populate_returns_none_when_id_does_not_match(service_cluster_controller, service_api_route_controller):
    """Returns None when the fetched service_id does not match the JWT iss claim."""
    service_cluster_controller.service_id = None
    service_cluster_controller.save()

    with mock.patch(MOCK_TARGET, return_value=str(uuid.uuid4())):
        result = populate_service_id(str(uuid.uuid4()))

    assert result is None


@pytest.mark.django_db
def test_populate_returns_cluster_and_writes_id_on_match(service_cluster_controller, service_api_route_controller):
    """Returns the ServiceCluster and writes service_id when metadata matches the JWT iss."""
    service_cluster_controller.service_id = None
    service_cluster_controller.save()

    target_id = str(uuid.uuid4())

    with mock.patch(MOCK_TARGET, return_value=target_id):
        result = populate_service_id(target_id)

    assert isinstance(result, ServiceCluster)
    assert str(result.service_id) == target_id
    service_cluster_controller.refresh_from_db()
    assert str(service_cluster_controller.service_id) == target_id


@pytest.mark.django_db
def test_populate_normalises_uppercase_issuer(service_cluster_controller, service_api_route_controller):
    """An uppercase iss claim is normalised and still matches a canonical stored UUID."""
    service_cluster_controller.service_id = None
    service_cluster_controller.save()

    canonical = str(uuid.uuid4())
    uppercase = canonical.upper()

    with mock.patch(MOCK_TARGET, return_value=canonical):
        result = populate_service_id(uppercase)

    assert isinstance(result, ServiceCluster)
    assert str(result.service_id) == canonical


@pytest.mark.django_db
def test_populate_race_condition_safe(service_cluster_controller, service_api_route_controller):
    """When update() returns 0 but exists() returns True (concurrent write), cluster is returned."""
    service_cluster_controller.service_id = None
    service_cluster_controller.save()

    target_id = str(uuid.uuid4())

    with mock.patch(MOCK_TARGET, return_value=target_id):
        with mock.patch.object(ServiceCluster.objects, "filter") as mock_filter:
            mock_qs = mock.MagicMock()
            mock_qs.update.return_value = 0  # another worker won the race
            mock_qs.exists.return_value = True  # but the id is now there
            mock_filter.return_value = mock_qs
            result = populate_service_id(target_id)

    assert isinstance(result, ServiceCluster)


@pytest.mark.django_db
def test_populate_swallows_db_exception(service_cluster_controller, service_api_route_controller):
    """Returns None when the HTTP client raises; never propagates the exception."""
    service_cluster_controller.service_id = None
    service_cluster_controller.save()

    target_id = str(uuid.uuid4())

    with mock.patch("aap_gateway_api.utils.service_id_sync.resources_client.GWResourceAPIClient") as mock_cls:
        mock_cls.return_value.get_service_metadata.side_effect = RuntimeError("network failure")
        result = populate_service_id(target_id)

    assert result is None


@pytest.mark.django_db
def test_populate_skips_unknown_service_type():
    """Does not probe clusters whose service type is not in DefaultServiceType."""
    from aap_gateway_api.models import ServiceCluster, ServiceType

    custom_type, _ = ServiceType.objects.get_or_create(name="custom-unknown-type")
    custom_cluster = ServiceCluster.objects.create(name="custom-cluster", service_type=custom_type)
    try:
        target_id = str(uuid.uuid4())
        _populate_cooldown.pop(target_id, None)
        try:
            with mock.patch(MOCK_TARGET) as mock_fetch:
                result = populate_service_id(target_id)
                mock_fetch.assert_not_called()
            assert result is None
        finally:
            _populate_cooldown.pop(target_id, None)
    finally:
        custom_cluster.delete()
        custom_type.delete()
