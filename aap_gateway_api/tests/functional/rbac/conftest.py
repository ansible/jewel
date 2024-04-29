import pytest
from ansible_base.rbac.models import RoleDefinition

from aap_gateway_api.models import Organization, Team, User


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
        users[None].append(f"User without membership {k}")

    return users
