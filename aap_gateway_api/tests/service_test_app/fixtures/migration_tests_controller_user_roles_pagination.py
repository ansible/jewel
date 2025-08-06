from ansible_base.rbac.models import DABContentType, RoleDefinition, RoleUserAssignment
from service_test_app.models import Organization, User


def setup():
    """
    This fixture creates many assignments to test that pagination is handled
    """
    assignment_count = 40
    content_type = DABContentType.objects.create(service='shared', app_label='service_test_app', model='organization')
    role_definition = RoleDefinition.objects.create(name='Organization Member', managed=True, content_type=content_type)
    user = User.objects.create(username='many-assignments-user')
    for i in range(assignment_count):
        organization = Organization.objects.create(name=f"organization-{i:02d}")
        RoleUserAssignment.objects.create(user=user, role_definition=role_definition, content_object=organization, content_type=content_type)
