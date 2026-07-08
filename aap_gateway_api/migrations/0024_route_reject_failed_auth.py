from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('aap_gateway_api', '0023_remove_console_service_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='route',
            name='reject_failed_auth',
            field=models.BooleanField(default=False, help_text='If true this route will return a 401 instead of allowing unauthenticated requests to the back end.'),
        ),
    ]
