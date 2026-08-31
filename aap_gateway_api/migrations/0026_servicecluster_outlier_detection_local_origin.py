from django.db import migrations, models


def set_local_origin_outlier_defaults(apps, schema_editor):
    """
    Apply the WebSocket-teardown-safe defaults on existing ServiceCluster rows
    so upgrades get the fix without a manual PATCH.
    """
    ServiceCluster = apps.get_model('aap_gateway_api', 'ServiceCluster')
    ServiceCluster.objects.all().update(
        outlier_detection_split_external_local_origin_errors=True,
        outlier_detection_consecutive_local_origin_failure=0,
    )


def unset_local_origin_outlier_defaults(apps, schema_editor):
    """
    Reverse: restore Envoy's original defaults (split off, threshold 5).
    """
    ServiceCluster = apps.get_model('aap_gateway_api', 'ServiceCluster')
    ServiceCluster.objects.all().update(
        outlier_detection_split_external_local_origin_errors=False,
        outlier_detection_consecutive_local_origin_failure=5,
    )


class Migration(migrations.Migration):
    dependencies = [
        ('aap_gateway_api', '0025_servicecluster_health_check_interval_default'),
    ]

    operations = [
        migrations.AddField(
            model_name='servicecluster',
            name='outlier_detection_split_external_local_origin_errors',
            field=models.BooleanField(
                default=True,
                help_text=(
                    'If true, locally-originated errors (e.g. upstream connection resets from WebSocket teardowns) '
                    'are tracked separately from externally-originated 5xx responses via consecutive_local_origin_failure '
                    'instead of consecutive_5xx. Setting this to false restores counting those events toward consecutive_5xx.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='servicecluster',
            name='outlier_detection_consecutive_local_origin_failure',
            field=models.PositiveIntegerField(
                default=0,
                help_text=(
                    'Number of consecutive locally originated failures (connect timeout, TCP reset/UC) before Envoy ejects '
                    'the host. Set to 0 to disable. CDS also emits enforcing_consecutive_local_origin_failure=0 so Envoy does '
                    'not treat an omitted value as its default of 5. Takes effect only when split_external_local_origin_errors '
                    'is true. Defaults to 0 so WebSocket teardowns do not eject the cluster. With this at 0, active health '
                    'checks are the remaining safety net for connect/UC.'
                ),
            ),
        ),
        migrations.AlterField(
            model_name='servicecluster',
            name='health_checks_enabled',
            field=models.BooleanField(
                default=True,
                help_text=(
                    'If true, health checks will be used to determine if a node is healthy. With local-origin consecutive '
                    'ejection disabled (the default), this is the remaining way to eject a host that fails with connect/UC.'
                ),
            ),
        ),
        migrations.RunPython(
            set_local_origin_outlier_defaults,
            unset_local_origin_outlier_defaults,
        ),
    ]
