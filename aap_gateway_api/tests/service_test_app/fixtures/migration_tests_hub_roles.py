from ansible_base.rbac.models import DABContentType, RoleDefinition
from service_test_app.models import Organization, Team, User


def setup():
    """
    This fixture creates data to represent hub's's role user assignments for migration to gateway.

    It creates the following list of permissions along with the corresponding User, Organization,
      Team, and RoleDefinition objects:

    User                     Role Definition                 Object
    -------------------------------------------------------------------------------------------------------------
    hub-team-admin           Team Admin                      Team: hub-admin-team
    hub-team-member          Team Member                     Team: hub-member-team
    hub-dummy-user           hub-dummy-role                  Organization: hub-dummy-organization

    The tests will check that hub-team-member is migrated and the others are not.

    """

    team_content_type = DABContentType.objects.get(service='shared', app_label='service_test_app', model='team')
    org_content_type = DABContentType.objects.get(service='shared', app_label='service_test_app', model='organization')

    access_levels = ['Admin', 'Member']
    resource_type = 'Team'
    organization = Organization.objects.create(name='hub-organization')
    for access_level in access_levels:
        role_definition_name = f'{resource_type} {access_level}'
        role_definition = RoleDefinition.objects.create(name=role_definition_name, managed=False, content_type=team_content_type)
        resource_name = f'hub-{access_level.lower()}-{resource_type.lower()}'
        resource = Team.objects.create(name=resource_name, organization=organization)
        username = f'hub-{resource_type.lower()}-{access_level.lower()}'
        user = User.objects.create(username=username)
        role_definition.give_permission(user, resource)

    # Also create a new role definition and permission
    other_user = User.objects.create(username='hub-dummy-user')
    other_org = Organization.objects.create(name='hub-dummy-organization')
    role_definition_dummy = RoleDefinition.objects.create(name='hub-dummy-role', content_type=org_content_type)
    role_definition_dummy.give_permission(other_user, other_org)
