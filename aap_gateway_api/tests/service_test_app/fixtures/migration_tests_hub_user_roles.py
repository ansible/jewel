from ansible_base.rbac.models import DABContentType, RoleDefinition, RoleUserAssignment
from service_test_app.models import Organization, Team, User


def setup():
    """
    This fixture creates data to represent hub's's role user assignments for migration to gateway.

    It creates the following list of RoleUserAssignments along with the corresponding User, Organization,
      Team, and RoleDefinition objects:

    User                     Role Definition                 Object
    -------------------------------------------------------------------------------------------------------------
    hub-team-admin           Team Admin                      Team: hub-admin-team
    hub-team-member          Team Member                     Team: hub-member-team
    hub-dummy-user           role-no-migrate                 Organization: hub-dummy-organization

    The tests will check that hub-team-member is migrated and the others are not.

    """

    access_levels = ['Admin', 'Member']
    resource_type = 'Team'
    organization = Organization.objects.create(name='hub-organization')
    team_content_type = DABContentType.objects.create(service='shared', app_label='service_test_app', model='team')
    for access_level in access_levels:
        role_definition_name = f'{resource_type} {access_level}'
        role_definition = RoleDefinition.objects.create(name=role_definition_name, managed=False, content_type=team_content_type)
        resource_name = f'hub-{access_level.lower()}-{resource_type.lower()}'
        resource = Team.objects.create(name=resource_name, organization=organization)
        username = f'hub-{resource_type.lower()}-{access_level.lower()}'
        user = User.objects.create(username=username)
        RoleUserAssignment.objects.create(user=user, role_definition=role_definition, content_object=resource, content_type=team_content_type)

    # Also create a role assignment that should not be migrated
    other_user = User.objects.create(username='hub-dummy-user')
    other_org = Organization.objects.create(name='hub-dummy-organization')
    org_content_type = DABContentType.objects.create(service='shared', app_label='service_test_app', model='organization')
    role_definition_no_migrate = RoleDefinition.objects.create(name='role-no-migrate', content_type=org_content_type)
    RoleUserAssignment.objects.create(user=other_user, role_definition=role_definition_no_migrate, content_object=other_org, content_type=org_content_type)
