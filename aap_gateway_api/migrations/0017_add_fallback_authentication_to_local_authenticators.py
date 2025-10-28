from django.db import migrations


def add_fallback_authentication_to_local_authenticators(apps, schema_editor):
    """
    Add fallback_authentication configuration to all local authenticators
    """
    # Get the model using apps.get_model
    Authenticator = apps.get_model('dab_authentication.Authenticator')

    # Find all local authenticators
    local_authenticators = Authenticator.objects.filter(
        type='ansible_base.authentication.authenticator_plugins.local'
    )

    fallback_config = [
        "aap_gateway_api.authentication.fallbacks.controller"
    ]

    for authenticator in local_authenticators:
        # Check if fallback_authentication is already configured
        configuration = authenticator.configuration or {}
        if 'fallback_authentication' not in configuration:
            configuration['fallback_authentication'] = fallback_config
            authenticator.configuration = configuration
            authenticator.save()


def remove_fallback_authentication_from_local_authenticators(apps, schema_editor):
    """
    Remove fallback_authentication configuration from all local authenticators
    """
    # Get the model using apps.get_model
    Authenticator = apps.get_model('dab_authentication.Authenticator')

    # Find all local authenticators
    local_authenticators = Authenticator.objects.filter(
        type='ansible_base.authentication.authenticator_plugins.local'
    )

    for authenticator in local_authenticators:
        configuration = authenticator.configuration or {}
        if 'fallback_authentication' in configuration:
            del configuration['fallback_authentication']
            authenticator.configuration = configuration
            authenticator.save()


class Migration(migrations.Migration):

    dependencies = [
        ('aap_gateway_api', '0016_route_enable_mtls_cacertificate'),
    ]

    operations = [
        migrations.RunPython(
            add_fallback_authentication_to_local_authenticators,
            remove_fallback_authentication_from_local_authenticators,
        ),
    ]
