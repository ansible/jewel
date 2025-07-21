from ansible_base.rbac.models import ContentType, RoleDefinition, RoleUserAssignment
from service_test_app.models import Organization, User


def setup():
    """
    This fixture creates many assignments to test that pagination is handled
    """
    assignment_count = 40
    content_type = ContentType.objects.get_for_model(Organization, for_concrete_model=False)
    role_definition = RoleDefinition.objects.create(name='Organization Member', managed=True, content_type=content_type)
    user = User.objects.create(username='many-assignments-user')
    for i in range(assignment_count):
        organization = Organization.objects.create(name=f"organization-{i:02d}")
        RoleUserAssignment.objects.create(user=user, role_definition=role_definition, content_object=organization, content_type=content_type)
