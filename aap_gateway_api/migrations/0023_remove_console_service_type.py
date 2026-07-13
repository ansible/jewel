from django.db import migrations


class Migration(migrations.Migration):
    """Convergence migration: merges the 0021 and 0022 branches.

    The data cleanup previously performed here (removing console ServiceType
    and RED_HAT_CONSOLE_URL preference) is now handled by the post_migrate
    signal handler remove_console_service_type() in preloaded_data.py.
    """

    dependencies = [
        ("aap_gateway_api", "0021_remove_runtime_feature_flags_ui_preference"),
        ("aap_gateway_api", "0022_usersessionmembership"),
    ]

    operations = []
