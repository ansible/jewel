from django.db import migrations, models


def set_split_external_local_origin_errors(apps, schema_editor):
    """
    Set outlier_detection_split_external_local_origin_errors=True for all
    existing ServiceCluster rows so that deployments upgrading from older
    versions immediately get the fix without manual intervention.
    """
    ServiceCluster = apps.get_model('aap_gateway_api', 'ServiceCluster')
    ServiceCluster.objects.all().update(
        outlier_detection_split_external_local_origin_errors=True,
    )


def unset_split_external_local_origin_errors(apps, schema_editor):
    """
    Reverse: reset to False (Envoy's original default) for rollback safety.
    """
    ServiceCluster = apps.get_model('aap_gateway_api', 'ServiceCluster')
    ServiceCluster.objects.all().update(
        outlier_detection_split_external_local_origin_errors=False,
    )


class Migration(migrations.Migration):
    dependencies = [
        ('aap_gateway_api', '0022_usersessionmembership'),
    ]

    operations = [
        migrations.AddField(
            model_name='servicecluster',
            name='outlier_detection_split_external_local_origin_errors',
            field=models.BooleanField(
                default=True,
                help_text=(
                    'If true, locally-originated errors (e.g. upstream connection resets from WebSocket teardowns) '
                    'are tracked separately from externally-originated 5xx responses. This prevents WebSocket connection '
                    'resets from counting toward the consecutive gateway failure threshold and causing cluster ejections.'
                ),
            ),
        ),
        migrations.RunPython(
            set_split_external_local_origin_errors,
            unset_split_external_local_origin_errors,
        ),
    ]
