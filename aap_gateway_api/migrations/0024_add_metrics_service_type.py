from django.conf import settings
from django.db import migrations


def add_metrics_service_type(apps, schema_editor):
    ServiceType = apps.get_model("aap_gateway_api", "ServiceType")
    User = apps.get_model(settings.AUTH_USER_MODEL)

    if ServiceType.objects.filter(name="metrics").exists():
        return

    system_user = User.all_objects.filter(username=settings.SYSTEM_USERNAME).first()
    st = ServiceType(
        name="metrics",
        ping_url="/api/metrics/v1/ping/",
        login_path=None,
        logout_path=None,
        service_index_path="/v1/service-index/",
    )
    st.created_by = system_user
    st.modified_by = system_user
    st.save()


class Migration(migrations.Migration):
    dependencies = [
        ("aap_gateway_api", "0023_remove_console_service_type"),
    ]

    operations = [
        migrations.RunPython(add_metrics_service_type, migrations.RunPython.noop),
    ]
