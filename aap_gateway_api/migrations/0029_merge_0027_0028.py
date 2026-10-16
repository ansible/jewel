from django.db import migrations


class Migration(migrations.Migration):
    """Rejoin the health-check and service-key migration branches."""

    dependencies = [
        ("aap_gateway_api", "0027_merge_0025_0026"),
        ("aap_gateway_api", "0028_alter_servicekey_algorithm_and_more"),
    ]

    operations = []
