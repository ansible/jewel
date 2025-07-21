from ansible_base.rbac.models import ContentType, RoleDefinition, RoleUserAssignment
from service_test_app.models import Organization, Team, User


def setup():
    """
    This fixture creates data to represent controller's role user assignments for migration to gateway.

    It creates the following list of RoleUserAssignments along with the corresponding User, Organization,
      Team, and RoleDefinition objects:

    User                            Role Definition                 Object
    -------------------------------------------------------------------------------------------------------------
    controller-organization-admin   Organization Admin              Organization: controller-admin-organization
    controller-organization-member  Organization Member             Organization: controller-member-organization
    controller-team-admin           Team Admin                      Team: controller-admin-team
    controller-team-member          Team Member                     Team: controller-member-team
    controller-platform-auditor     Platform Auditor                None
    controller-dummy-user           role-no-migrate                 Organization: controller-dummy-organization

    The tests will check that the first four are migrated and the last one is not.
    """
    resource_types = ['Organization', 'Team']
    access_levels = ['Admin', 'Member']
    for resource_type in resource_types:
        for access_level in access_levels:
            role_definition_name = f'{resource_type} {access_level}'
            resource_name = f'controller-{access_level.lower()}-{resource_type.lower()}'
            resource = None
            if resource_type == 'Organization':
                resource = Organization.objects.create(name=resource_name)
            else:
                resource = Team.objects.create(name=resource_name, organization=Organization.objects.first())
            username = f'controller-{resource_type.lower()}-{access_level.lower()}'
            user = User.objects.create(username=username)
            content_type = ContentType.objects.get_for_model(resource)
            role_definition = RoleDefinition.objects.create(name=role_definition_name, managed=True, content_type=content_type)
            RoleUserAssignment.objects.create(user=user, role_definition=role_definition, content_object=resource, content_type=content_type)

    # Create a platform-wide role that has no object
    platform_user = User.objects.create(username='controller-platform-auditor')
    platform_role_definition = RoleDefinition.objects.create(name='Platform Auditor', managed=True)
    RoleUserAssignment.objects.create(user=platform_user, role_definition=platform_role_definition)

    # Also create a role assignment that should not be migrated
    other_user = User.objects.create(username='controller-dummy-user')
    other_org = Organization.objects.create(name='controller-dummy-organization')
    org_content_type = ContentType.objects.get_for_model(other_org, for_concrete_model=True)
    role_definition_no_migrate = RoleDefinition.objects.create(name='role-no-migrate', content_type=org_content_type)
    RoleUserAssignment.objects.create(user=other_user, role_definition=role_definition_no_migrate, content_object=other_org, content_type=org_content_type)
