from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('aap_gateway_api', '0024_route_reject_failed_basic_auth'),
    ]

    operations = [
        migrations.AlterField(
            model_name='servicecluster',
            name='health_check_interval_seconds',
            field=models.PositiveIntegerField(default=30, help_text='The time between health check requests.'),
        ),
    ]
