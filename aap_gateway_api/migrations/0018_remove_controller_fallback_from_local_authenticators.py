"""
Remove Controller fallback authentication from local authenticators .

The Controller fallback authenticator is removed ; this migration strips
fallback_authentication from existing local authenticators.
"""

from django.db import migrations


def remove_fallback_authentication_from_local_authenticators(apps, schema_editor):
    """
    Remove fallback_authentication configuration from all local authenticators.
    """
    Authenticator = apps.get_model('dab_authentication.Authenticator')

    local_authenticators = Authenticator.objects.filter(
        type='ansible_base.authentication.authenticator_plugins.local'
    )

    for authenticator in local_authenticators:
        configuration = authenticator.configuration or {}
        if 'fallback_authentication' in configuration:
            del configuration['fallback_authentication']
            authenticator.configuration = configuration
            authenticator.save(update_fields=['configuration'])


def add_fallback_authentication_to_local_authenticators(apps, schema_editor):
    """
    Re-add fallback_authentication for migration reverse (rollback).
    """
    Authenticator = apps.get_model('dab_authentication.Authenticator')

    local_authenticators = Authenticator.objects.filter(
        type='ansible_base.authentication.authenticator_plugins.local'
    )

    fallback_config = [
        "aap_gateway_api.authentication.fallbacks.controller"
    ]

    for authenticator in local_authenticators:
        configuration = authenticator.configuration or {}
        if 'fallback_authentication' not in configuration:
            configuration['fallback_authentication'] = fallback_config
            authenticator.configuration = configuration
            authenticator.save(update_fields=['configuration'])


class Migration(migrations.Migration):

    dependencies = [
        ('aap_gateway_api', '0017_add_fallback_authentication_to_local_authenticators'),
    ]

    operations = [
        migrations.RunPython(
            remove_fallback_authentication_from_local_authenticators,
            add_fallback_authentication_to_local_authenticators,
        ),
    ]
