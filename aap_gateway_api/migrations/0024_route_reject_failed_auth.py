from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('aap_gateway_api', '0023_remove_console_service_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='route',
            name='reject_failed_auth',
            field=models.BooleanField(
                default=False,
                help_text='If true, requests with invalid Basic credentials will receive a 401 instead of being passed to the back end as anonymous.',
            ),
        ),
    ]
