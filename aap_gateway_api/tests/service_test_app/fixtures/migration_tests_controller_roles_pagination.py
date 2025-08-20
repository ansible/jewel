from ansible_base.rbac.models import DABContentType, RoleDefinition
from service_test_app.models import Organization, User


def setup():
    """
    This fixture creates many assignments to test that pagination is handled
    """
    assignment_count = 40
    content_type = DABContentType.objects.get(service='shared', app_label='service_test_app', model='organization')
    role_definition = RoleDefinition.objects.create(name='Organization Member', managed=True, content_type=content_type)
    user = User.objects.create(username='many-assignments-user')
    for i in range(assignment_count):
        organization = Organization.objects.create(name=f"organization-{i:02d}")
        role_definition.give_permission(user, organization)
