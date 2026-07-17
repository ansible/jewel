import uuid
from unittest import mock

import pytest

from aap_gateway_api.models import ServiceCluster
from aap_gateway_api.utils.service_id_sync import _fetch_service_id_for_route, populate_missing_service_ids, try_populate_service_id  # noqa: E402

MOCK_TARGET = "aap_gateway_api.utils.service_id_sync._fetch_service_id_for_route"


# ---------------------------------------------------------------------------
# _fetch_service_id_for_route
# ---------------------------------------------------------------------------


def test_fetch_returns_none_on_non_200(service_api_route_controller):
    """Returns None when the metadata endpoint returns a non-200 status."""
    resp = mock.Mock()
    resp.status_code = 500

    with mock.patch("aap_gateway_api.utils.service_id_sync.resources_client.GWResourceAPIClient") as mock_client_cls:
        mock_client_cls.return_value.get_service_metadata.return_value = resp
        result = _fetch_service_id_for_route(service_api_route_controller)

    assert result is None


def test_fetch_returns_none_on_exception(service_api_route_controller):
    """Returns None and logs when the HTTP call raises an exception."""
    with mock.patch("aap_gateway_api.utils.service_id_sync.resources_client.GWResourceAPIClient") as mock_client_cls:
        mock_client_cls.return_value.get_service_metadata.side_effect = ConnectionError("boom")
        result = _fetch_service_id_for_route(service_api_route_controller)

    assert result is None


def test_fetch_returns_service_id_string(service_api_route_controller):
    """Returns the service_id string from a successful metadata response."""
    expected = str(uuid.uuid4())
    resp = mock.Mock()
    resp.status_code = 200
    resp.json.return_value = {"service_id": expected}

    with mock.patch("aap_gateway_api.utils.service_id_sync.resources_client.GWResourceAPIClient") as mock_client_cls:
        mock_client_cls.return_value.get_service_metadata.return_value = resp
        result = _fetch_service_id_for_route(service_api_route_controller)

    assert result == expected


# ---------------------------------------------------------------------------
# populate_missing_service_ids
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_populate_skips_gateway_cluster(service_cluster_gateway):
    """GATEWAY-type clusters are never touched (they self-assign service_id)."""
    service_cluster_gateway.service_id = None
    service_cluster_gateway.save()

    with mock.patch(MOCK_TARGET) as mock_fetch:
        populated, failed = populate_missing_service_ids()

    mock_fetch.assert_not_called()
    assert populated == []
    assert failed == []


@pytest.mark.django_db
def test_populate_skips_cluster_with_no_api_route(service_cluster_controller):
    """Clusters without a ServiceAPIRoute are reported as failed."""
    service_cluster_controller.service_id = None
    service_cluster_controller.save()

    with mock.patch(MOCK_TARGET) as mock_fetch:
        populated, failed = populate_missing_service_ids()

    mock_fetch.assert_not_called()
    assert service_cluster_controller.name in failed


@pytest.mark.django_db
def test_populate_skips_cluster_that_already_has_service_id(service_cluster_controller, service_api_route_controller):
    """Clusters with an existing service_id are skipped by default."""
    service_cluster_controller.service_id = uuid.uuid4()
    service_cluster_controller.save()

    with mock.patch(MOCK_TARGET) as mock_fetch:
        populated, failed = populate_missing_service_ids()

    mock_fetch.assert_not_called()
    assert populated == []
    assert failed == []


@pytest.mark.django_db
def test_populate_writes_service_id_on_success(service_cluster_controller, service_api_route_controller):
    """A null-id cluster gets its service_id populated from the metadata response."""
    service_cluster_controller.service_id = None
    service_cluster_controller.save()

    new_id = str(uuid.uuid4())

    with mock.patch(MOCK_TARGET, return_value=new_id):
        populated, failed = populate_missing_service_ids()

    assert service_cluster_controller.name in populated
    assert failed == []
    service_cluster_controller.refresh_from_db()
    assert str(service_cluster_controller.service_id) == new_id


@pytest.mark.django_db
def test_populate_records_failure_when_fetch_returns_none(service_cluster_controller, service_api_route_controller):
    """A cluster is added to failed when the metadata fetch returns None."""
    service_cluster_controller.service_id = None
    service_cluster_controller.save()

    with mock.patch(MOCK_TARGET, return_value=None):
        populated, failed = populate_missing_service_ids()

    assert service_cluster_controller.name in failed
    assert populated == []
    service_cluster_controller.refresh_from_db()
    assert service_cluster_controller.service_id is None


@pytest.mark.django_db
def test_populate_force_overwrites_existing_service_id(service_cluster_controller, service_api_route_controller):
    """With force=True, clusters that already have a service_id are re-fetched and overwritten."""
    original_id = uuid.uuid4()
    service_cluster_controller.service_id = original_id
    service_cluster_controller.save()

    new_id = str(uuid.uuid4())

    with mock.patch(MOCK_TARGET, return_value=new_id):
        populated, failed = populate_missing_service_ids(force=True)

    assert service_cluster_controller.name in populated
    service_cluster_controller.refresh_from_db()
    assert str(service_cluster_controller.service_id) == new_id


@pytest.mark.django_db
def test_populate_force_failure_leaves_existing_id(service_cluster_controller, service_api_route_controller):
    """With force=True, if fetch fails the existing service_id is left unchanged."""
    original_id = uuid.uuid4()
    service_cluster_controller.service_id = original_id
    service_cluster_controller.save()

    with mock.patch(MOCK_TARGET, return_value=None):
        populated, failed = populate_missing_service_ids(force=True)

    assert service_cluster_controller.name in failed
    service_cluster_controller.refresh_from_db()
    assert service_cluster_controller.service_id == original_id


@pytest.mark.django_db
def test_populate_race_condition_safe(service_cluster_controller, service_api_route_controller):
    """Concurrent calls to populate are idempotent: the winner writes, the loser confirms."""
    service_cluster_controller.service_id = None
    service_cluster_controller.save()

    shared_id = str(uuid.uuid4())

    # Simulate the loser: update() returns 0 rows (another process already wrote),
    # but the cluster now has the id so the exists() check passes.
    with mock.patch(MOCK_TARGET, return_value=shared_id):
        with mock.patch.object(ServiceCluster.objects.__class__, "filter") as mock_filter:
            mock_qs = mock.MagicMock()
            mock_qs.update.return_value = 0  # loser: 0 rows updated
            mock_qs.exists.return_value = True  # but id is already there
            mock_filter.return_value = mock_qs
            populated, failed = populate_missing_service_ids()

    assert service_cluster_controller.name in populated


# ---------------------------------------------------------------------------
# try_populate_service_id
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_try_populate_returns_false_when_no_null_clusters(service_cluster_controller, service_api_route_controller):
    """Returns False when all clusters already have a service_id."""
    service_cluster_controller.service_id = uuid.uuid4()
    service_cluster_controller.save()

    result = try_populate_service_id(str(uuid.uuid4()))
    assert result is False


@pytest.mark.django_db
def test_try_populate_returns_false_when_no_route(service_cluster_controller):
    """Returns False when the null-id cluster has no ServiceAPIRoute."""
    service_cluster_controller.service_id = None
    service_cluster_controller.save()

    result = try_populate_service_id(str(uuid.uuid4()))
    assert result is False


@pytest.mark.django_db
def test_try_populate_returns_false_when_id_does_not_match(service_cluster_controller, service_api_route_controller):
    """Returns False when the fetched service_id does not match the JWT iss claim."""
    service_cluster_controller.service_id = None
    service_cluster_controller.save()

    with mock.patch(MOCK_TARGET, return_value=str(uuid.uuid4())):
        result = try_populate_service_id(str(uuid.uuid4()))  # different UUID

    assert result is False


@pytest.mark.django_db
def test_try_populate_returns_true_and_writes_on_match(service_cluster_controller, service_api_route_controller):
    """Returns True and sets service_id when a cluster's metadata matches the JWT iss claim."""
    service_cluster_controller.service_id = None
    service_cluster_controller.save()

    target_id = str(uuid.uuid4())

    with mock.patch(MOCK_TARGET, return_value=target_id):
        result = try_populate_service_id(target_id)

    assert result is True
    service_cluster_controller.refresh_from_db()
    assert str(service_cluster_controller.service_id) == target_id


@pytest.mark.django_db
def test_try_populate_swallows_fetch_exception(service_cluster_controller, service_api_route_controller):
    """Returns False when the HTTP call raises; _fetch_service_id_for_route swallows it."""
    service_cluster_controller.service_id = None
    service_cluster_controller.save()

    target_id = str(uuid.uuid4())

    # Mock the HTTP client so the real _fetch_service_id_for_route runs its internal try/except.
    with mock.patch("aap_gateway_api.utils.service_id_sync.resources_client.GWResourceAPIClient") as mock_cls:
        mock_cls.return_value.get_service_metadata.side_effect = RuntimeError("network failure")
        result = try_populate_service_id(target_id)

    assert result is False
