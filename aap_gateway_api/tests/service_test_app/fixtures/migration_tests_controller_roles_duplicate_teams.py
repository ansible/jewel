from ansible_base.rbac.models import DABContentType, RoleDefinition
from service_test_app.models import Organization, Team, User


def setup():
    """
    This fixture creates two teams with the same name in different organizations then assigns permissions on them
    """
    org1 = Organization.objects.create(name="Organization 1")
    org2 = Organization.objects.create(name="Organization 2")

    team1 = Team.objects.create(organization=org1, name="test-team")
    team2 = Team.objects.create(organization=org2, name="test-team")
    content_type = DABContentType.objects.get(service='shared', app_label='service_test_app', model='team')
    role_definition = RoleDefinition.objects.create(name='Team Member', managed=True, content_type=content_type)
    user = User.objects.create(username='duplicate-teams-user')
    role_definition.give_permission(user, team1)
    role_definition.give_permission(user, team2)
