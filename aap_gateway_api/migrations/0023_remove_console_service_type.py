from django.db import migrations


def remove_console_service_type(apps, schema_editor):
    ServiceType = apps.get_model("aap_gateway_api", "ServiceType")
    ServiceType.objects.filter(name="console").delete()

    Preference = apps.get_model("aap_gateway_api", "Preference")
    Preference.objects.filter(
        section="analytics",
        name__in=["RED_HAT_CONSOLE_URL", "REDHAT_USERNAME", "REDHAT_PASSWORD"],
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("aap_gateway_api", "0022_usersessionmembership"),
    ]

    operations = [
        migrations.RunPython(
            remove_console_service_type,
            migrations.RunPython.noop,
        ),
    ]
