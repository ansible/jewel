from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("aap_gateway_api", "0023_remove_console_service_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="MigrateServiceDataLastRolePK",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("service_slug", models.CharField(max_length=255)),
                ("assignment_type", models.CharField(choices=[("user", "User"), ("team", "Team")], max_length=4)),
                ("last_pk", models.BigIntegerField(default=0)),
            ],
            options={
                "verbose_name": "Migrate Service Data Role Assignment Cursor",
                "verbose_name_plural": "Migrate Service Data Role Assignment Cursors",
                "unique_together": {("service_slug", "assignment_type")},
            },
        ),
    ]
