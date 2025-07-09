from service_test_app.models import Organization, Team, User


def setup():
    """Create test data for Hub superuser migration tests."""

    # Create organizations
    org1 = Organization.objects.create(name="TestOrg1")
    org2 = Organization.objects.create(name="TestOrg2")

    # Create teams (optional for hub, but good to have for testing)
    team1 = Team.objects.create(name="TestTeam1", organization=org1)
    team2 = Team.objects.create(name="TestTeam2", organization=org2)

    # Create regular admin user (will be used for migration)
    admin_user = User.objects.create(username="admin", is_superuser=True)
    admin_user.set_password("controller_admin_pass")
    admin_user.save()

    # Create hub superuser who should be synced with Gateway superuser status
    hub_super = User.objects.create(username="hub_super", is_superuser=True)
    hub_super.organizations.set([org1])
    hub_super.teams.set([team1])

    # Create hub regular user who should remain regular
    hub_regular = User.objects.create(username="hub_regular", is_superuser=False)
    hub_regular.organizations.set([org2])
    hub_regular.teams.set([team2])
