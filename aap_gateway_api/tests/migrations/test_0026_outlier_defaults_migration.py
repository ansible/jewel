import importlib

import pytest
from django.apps import apps

from aap_gateway_api.models import ServiceCluster, ServiceType

_migration = importlib.import_module("aap_gateway_api.migrations.0026_servicecluster_outlier_detection_local_origin")
set_defaults = _migration.set_local_origin_outlier_defaults
unset_defaults = _migration.unset_local_origin_outlier_defaults


@pytest.mark.parametrize(
    "initial_values",
    [
        [(False, 5), (True, 8), (False, 0)],
        [(True, 3), (False, 11)],
    ],
    ids=["mixed-initial-values", "alternate-values"],
)
def test_forward_and_reverse_set_exact_defaults_idempotently(db, initial_values):
    service_type, _ = ServiceType.objects.get_or_create(name="migration-snapshot-outlier-tests")
    clusters = []
    for index, (split, threshold) in enumerate(initial_values):
        clusters.append(
            ServiceCluster.objects.create(
                name=f"Migration Snapshot Cluster {index}",
                service_type=service_type,
                outlier_detection_split_external_local_origin_errors=split,
                outlier_detection_consecutive_local_origin_failure=threshold,
                outlier_detection_enabled=index % 2 == 0,
                health_checks_enabled=index % 2 == 1,
                outlier_detection_interval_seconds=15 + index,
                healthy_panic_threshold=20 + index,
            )
        )
    original = {
        cluster.pk: {
            "name": cluster.name,
            "service_type_id": cluster.service_type_id,
            "outlier_detection_enabled": cluster.outlier_detection_enabled,
            "health_checks_enabled": cluster.health_checks_enabled,
            "outlier_detection_interval_seconds": cluster.outlier_detection_interval_seconds,
            "healthy_panic_threshold": cluster.healthy_panic_threshold,
        }
        for cluster in clusters
    }

    set_defaults(apps, None)
    for cluster in clusters:
        cluster.refresh_from_db()
        assert cluster.outlier_detection_split_external_local_origin_errors is True
        assert cluster.outlier_detection_consecutive_local_origin_failure == 0
    first_forward = {cluster.pk: cluster.modified for cluster in clusters}

    set_defaults(apps, None)
    for cluster in clusters:
        cluster.refresh_from_db()
        assert cluster.outlier_detection_split_external_local_origin_errors is True
        assert cluster.outlier_detection_consecutive_local_origin_failure == 0
        assert cluster.modified == first_forward[cluster.pk]
        assert {
            "name": cluster.name,
            "service_type_id": cluster.service_type_id,
            "outlier_detection_enabled": cluster.outlier_detection_enabled,
            "health_checks_enabled": cluster.health_checks_enabled,
            "outlier_detection_interval_seconds": cluster.outlier_detection_interval_seconds,
            "healthy_panic_threshold": cluster.healthy_panic_threshold,
        } == original[cluster.pk]

    unset_defaults(apps, None)
    for cluster in clusters:
        cluster.refresh_from_db()
        assert cluster.outlier_detection_split_external_local_origin_errors is False
        assert cluster.outlier_detection_consecutive_local_origin_failure == 5
    first_reverse = {cluster.pk: cluster.modified for cluster in clusters}

    unset_defaults(apps, None)
    for cluster in clusters:
        cluster.refresh_from_db()
        assert cluster.pk in original
        assert cluster.outlier_detection_split_external_local_origin_errors is False
        assert cluster.outlier_detection_consecutive_local_origin_failure == 5
        assert cluster.modified == first_reverse[cluster.pk]
        assert {
            "name": cluster.name,
            "service_type_id": cluster.service_type_id,
            "outlier_detection_enabled": cluster.outlier_detection_enabled,
            "health_checks_enabled": cluster.health_checks_enabled,
            "outlier_detection_interval_seconds": cluster.outlier_detection_interval_seconds,
            "healthy_panic_threshold": cluster.healthy_panic_threshold,
        } == original[cluster.pk]
