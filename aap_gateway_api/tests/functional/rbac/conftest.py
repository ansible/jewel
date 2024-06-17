import pytest
from ansible_base.authentication.models import Authenticator, AuthenticatorMap
from ansible_base.rbac.models import RoleDefinition

from aap_gateway_api.models import Organization, Team, User


@pytest.mark.parametrize('user_type', ['unauthenticated', 'user', 'platform_auditor', 'superuser'])
class TestPermissionsBase:
    @pytest.fixture(scope="function", autouse=True)
    def init_api_client(self, user_type, unauthenticated_api_client, user_api_client, user):
        if user_type in ['platform_auditor', 'superuser']:
            user.is_platform_auditor = user_type == 'platform_auditor'
            user.is_superuser = user_type == 'superuser'
            user.save()

        self.api_client = unauthenticated_api_client if user_type == 'unauthenticated' else user_api_client


@pytest.fixture
def org_admin_rd():
    return RoleDefinition.objects.get(name='Organization Admin')


@pytest.fixture
def org_member_rd():
    return RoleDefinition.objects.get(name='Organization Member')


@pytest.fixture
def admin_rd():
    return RoleDefinition.objects.get(name='Team Admin')


@pytest.fixture
def member_rd():
    return RoleDefinition.objects.get(name='Team Member')


def mk_organization(name, description=''):
    return Organization.objects.create(name=name, description=description)


def mk_team(team_name, organization, description=''):
    return Team.objects.create(name=team_name, organization=organization, description=description)


def mk_user(username, password='password', is_superuser=False, first_name='', last_name='', email=''):
    return User.objects.create(username=username, password=password, is_superuser=is_superuser, first_name=first_name, last_name=last_name, email=email)


@pytest.fixture
def authenticator_local(randname):
    return Authenticator.objects.create(
        name=randname("Local Authenticator"), type='ansible_base.authentication.authenticator_plugins.local', enabled=True, configuration={}
    )


@pytest.fixture
def authenticator_map(authenticator_local, randname):
    return AuthenticatorMap.objects.create(
        name=randname("Authenticator Map for Organization"),
        authenticator=authenticator_local,
        revoke=False,
        map_type='organization',
        organization=randname("Organization"),
        triggers=dict(always={}, never={}),
        order=1,
    )


@pytest.fixture
def organizations():
    """There are 6 organizations"""
    orgs = []
    for i in range(7):
        org = mk_organization(f"Org {i + 1}")
        orgs.append(org)
    return orgs


@pytest.fixture
@pytest.mark.django_db
def teams(organizations):
    """Each organization has 2 teams (12 total)"""
    teams = {}
    team_number = 0
    for i, org in enumerate(organizations):
        teams[org] = []
        for _ in range(2):
            team_number += 1
            teams[org].append(mk_team(f"Team {team_number} ({org.name})", org))
    return teams


@pytest.fixture
@pytest.mark.django_db
def users(organizations, teams):
    """
    - Each Team has 3 users (Team Member, Team Admin, Team Member+Admin)
    - Each Organization has 3 users (Org Member, Org Admin, Org Member+Admin)
    - 2 users don't belong to any organization or team"""
    users = {}
    for i, org in enumerate(organizations):
        for j, org_team in enumerate(teams[org]):
            users[org_team] = []
            for role in ["Team Member", "Team Admin", "Team Member+Admin"]:
                users[org_team].append(mk_user(f"{role} ({org_team.name})"))

        users[org] = []
        for role in ["Org Member", "Org Admin", "Org Member+Admin"]:
            users[org].append(mk_user(f"{role} ({org.name})"))

    users[None] = []
    for k in range(2):
        users[None].append(mk_user(f"User without membership {k}"))

    return users


def associate_users(users, teams, organizations):
    """Making memberships:
    Each Team has:
    - 1 Team Member
    - 1 Team Admin
    - 1 Team Member+Admin
    Each Org has:
    - 1 Org Member
    - 1 Org Admin
    - 1 Org Member+Admin
    """
    for org in organizations:
        for org_team in teams[org]:
            for i, team_user in enumerate(users[org_team], 1):
                if i == 1:
                    # Add Team Member
                    org_team.add_member(team_user)
                elif i == 2:
                    # Add Team Admin
                    org_team.add_admin(team_user)
                elif i == 3:
                    # Add Team Member+Admin
                    org_team.add_member(team_user)
                    org_team.add_admin(team_user)

        for i, org_user in enumerate(users[org], 1):
            if i == 1:
                # Add Org Member
                org.add_member(org_user)
            elif i == 2:
                # Add Org Admin
                org.add_admin(org_user)
            elif i == 3:
                # Add Org Member+Admin
                org.add_member(org_user)
                org.add_admin(org_user)


def api_get_and_assert(url, api_client, expected_objects, order_by="name"):
    response = api_client.get(url, {"order_by": order_by})
    assert response.status_code == 200
    results = response.data["results"]
    assert len(results) == len(expected_objects)
    for i in range(len(expected_objects)):
        assert results[i]["name"] == expected_objects[i].name, f"result: {results[i]['name']}, expected: {expected_objects[i].name}"
