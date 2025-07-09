from service_test_app.models import Organization, Team, User


def setup():
    """Create test data for Controller superuser migration tests."""

    # Create organizations
    org1 = Organization.objects.create(name="TestOrg1")
    org2 = Organization.objects.create(name="TestOrg2")

    # Create teams
    team1 = Team.objects.create(name="TestTeam1", organization=org1)
    team2 = Team.objects.create(name="TestTeam2", organization=org2)

    # Create regular admin user (will be used for migration)
    admin_user = User.objects.create(username="admin", is_superuser=True)
    admin_user.set_password("controller_admin_pass")
    admin_user.save()

    # Create controller superuser who should be promoted to Gateway superuser
    controller_super = User.objects.create(username="controller_super", is_superuser=True)
    controller_super.organizations.set([org1])
    controller_super.teams.set([team1])

    # Create controller regular user who should remain regular
    controller_regular = User.objects.create(username="controller_regular", is_superuser=False)
    controller_regular.organizations.set([org2])
    controller_regular.teams.set([team2])
