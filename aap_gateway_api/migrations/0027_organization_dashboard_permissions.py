from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('aap_gateway_api', '0026_servicecluster_outlier_detection_local_origin'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='organization',
            options={
                'permissions': [
                    ('member_organization', 'User is a member of this organization'),
                    ('view_automation_dashboard', 'Can view the automation dashboard for this organization'),
                    ('change_automation_dashboard', 'Can edit automation dashboard settings for this organization'),
                ],
            },
        ),
    ]
