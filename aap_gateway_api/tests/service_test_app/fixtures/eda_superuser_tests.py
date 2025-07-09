from service_test_app.models import Organization, Team, User


def setup():
    """Create test data for EDA superuser migration tests."""

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

    # Create EDA superuser who should be synced with Gateway superuser status
    eda_super = User.objects.create(username="eda_super", is_superuser=True)
    eda_super.teams.set([team1])

    # Create EDA regular user who should remain regular
    eda_regular = User.objects.create(username="eda_regular", is_superuser=False)
    eda_regular.teams.set([team2])
