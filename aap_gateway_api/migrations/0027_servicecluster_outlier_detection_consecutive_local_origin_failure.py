from django.db import migrations, models


def set_consecutive_local_origin_failure_zero(apps, schema_editor):
    """
    Disable consecutive local-origin ejection on existing ServiceCluster rows.
    Envoy treats an explicit 0 as disabled; omitting the field defaults to 5.
    """
    ServiceCluster = apps.get_model('aap_gateway_api', 'ServiceCluster')
    ServiceCluster.objects.all().update(
        outlier_detection_consecutive_local_origin_failure=0,
    )


def unset_consecutive_local_origin_failure(apps, schema_editor):
    """
    Reverse: restore Envoy's original default of 5 consecutive local-origin failures.
    """
    ServiceCluster = apps.get_model('aap_gateway_api', 'ServiceCluster')
    ServiceCluster.objects.all().update(
        outlier_detection_consecutive_local_origin_failure=5,
    )


class Migration(migrations.Migration):
    dependencies = [
        ('aap_gateway_api', '0026_servicecluster_outlier_detection_split_external_local_origin_errors'),
    ]

    operations = [
        migrations.AlterField(
            model_name='servicecluster',
            name='outlier_detection_split_external_local_origin_errors',
            field=models.BooleanField(
                default=True,
                help_text=(
                    'If true, locally-originated errors (e.g. upstream connection resets from WebSocket teardowns) '
                    'are tracked separately from externally-originated 5xx responses via consecutive_local_origin_failure '
                    'instead of consecutive_5xx.'
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
                    'the host. Set to 0 to disable. Takes effect only when split_external_local_origin_errors is true. '
                    'Defaults to 0 so WebSocket teardowns do not eject the cluster.'
                ),
            ),
        ),
        migrations.RunPython(
            set_consecutive_local_origin_failure_zero,
            unset_consecutive_local_origin_failure,
        ),
    ]
