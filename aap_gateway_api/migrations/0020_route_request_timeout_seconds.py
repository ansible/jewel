import django.core.validators
from django.db import migrations, models


def migrate_streaming_timeouts_forward(apps, schema_editor):
    """
    Migrate lightspeed streaming preferences into per-route timeout fields,
    then delete the old preferences.

    Lightspeed routes previously used global max_stream_duration and
    stream_idle_timeout preferences for their timeout and idle_timeout.
    Now that both are per-route fields, we bake the preference values
    into the routes so behaviour is preserved on upgrade.
    """
    Preference = apps.get_model('aap_gateway_api', 'Preference')
    Route = apps.get_model('aap_gateway_api', 'Route')

    old_prefs = dict(
        Preference.objects.filter(
            section='proxy', name__in=['max_stream_duration', 'stream_idle_timeout']
        ).values_list('name', 'raw_value')
    )

    # Use DB values if present, otherwise fall back to the old registered defaults
    max_stream_duration = int(old_prefs.get('max_stream_duration', 3600))
    stream_idle_timeout = int(old_prefs.get('stream_idle_timeout', 60))

    # Update the lightspeed (streaming) routes with the old preference values this is what the old xDS logic did
    Route.objects.filter(
        service_cluster__service_type__name='lightspeed',
    ).update(
        request_timeout_seconds=max_stream_duration,
        idle_timeout_seconds=stream_idle_timeout,
    )

    # Delete the old preferences from the database so we don't have orphaned values
    Preference.objects.filter(
        section='proxy', name__in=['max_stream_duration', 'stream_idle_timeout']
    ).delete()


def migrate_streaming_timeouts_reverse(apps, schema_editor):
    import warnings

    warnings.warn(
        "Rolling back this migration will not restore any custom "
        "values for the deleted preferences: "
        "['max_stream_duration', 'stream_idle_timeout']. "
        "The preference library will recreate them with default values.",
        stacklevel=1,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('aap_gateway_api', '0019_remove_use_controller_password_from_user'),
    ]

    operations = [
        migrations.AddField(
            model_name='route',
            name='request_timeout_seconds',
            field=models.PositiveIntegerField(
                blank=True,
                help_text=(
                    'The request timeout in seconds for this route. '
                    'Values below the global proxy request_timeout setting are rejected. '
                    'Leave null to use the global proxy timeout setting. '
                    'See effective_timeout_seconds for the computed value applied to the route.'
                ),
                null=True,
                validators=[django.core.validators.MaxValueValidator(604800)],
            ),
        ),
        migrations.AddField(
            model_name='route',
            name='idle_timeout_seconds',
            field=models.PositiveIntegerField(
                blank=True,
                help_text=(
                    'The idle timeout in seconds for this route. '
                    'Connections with no data transmitted within this period are closed. '
                    'Values below the global proxy idle_timeout setting are rejected. '
                    'Leave null to use the global proxy idle timeout setting. '
                    'See effective_idle_timeout_seconds for the computed value applied to the route.'
                ),
                null=True,
                validators=[django.core.validators.MaxValueValidator(86400)],
            ),
        ),
        migrations.RunPython(
            migrate_streaming_timeouts_forward,
            migrate_streaming_timeouts_reverse,
        ),
    ]
