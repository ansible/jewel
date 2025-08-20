from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import RoleDefinition
from service_test_app.models import Organization, Team, TestPermissionObject, User


def setup():
    """
    This fixture creates data to represent user permissions on controller objects that are not platform-wide
    so that we can confirm they are migrated to gateway and reference a RemoteObject
    """

    organization = Organization.objects.create(name='test-organization')

    # Create an object of model TestPermissionObject, which supports 'view' permission
    test_object = TestPermissionObject.objects.create(organization=organization)

    # Look up its content type, which will serialize to 'awx.testpermissionobject' and not 'shared.testpermissionobject'
    content_type = permission_registry.content_type_model.objects.get_for_model(TestPermissionObject)
    rd = RoleDefinition.objects.create_from_permissions(
        name='TestPermissionObject Viewer', permissions=['view_testpermissionobject'], content_type=content_type
    )
    # Create a user and a team
    user = User.objects.create(username='test-user')
    team = Team.objects.create(name='test-team', organization=organization)
    # Give them both the permission.
    # The RoleDefinition is a resource and will have an ansible_id in the resource registry
    # But the permission references an object that is not a resource
    rd.give_permission(user, test_object)
    rd.give_permission(team, test_object)
