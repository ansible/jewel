# Generated with AI assistance: Claude Code (Anthropic)

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("aap_gateway_api", "0017_add_fallback_authentication_to_local_authenticators"),
        ("sessions", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserSessionMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created", models.DateTimeField(default=django.utils.timezone.now, help_text="When this session was first tracked.")),
                (
                    "session",
                    models.OneToOneField(
                        help_text="The Django session associated with this membership.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="membership",
                        to="sessions.session",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        help_text="The user who owns this session.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="session_memberships",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "app_label": "aap_gateway_api",
            },
        ),
    ]
