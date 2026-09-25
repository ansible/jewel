from django.db import migrations


class Migration(migrations.Migration):
    """Converge the devel health-check and outlier-detection branches."""

    dependencies = [
        ("aap_gateway_api", "0025_servicecluster_health_check_interval_default"),
        ("aap_gateway_api", "0026_servicecluster_outlier_detection_local_origin"),
    ]

    operations = []
