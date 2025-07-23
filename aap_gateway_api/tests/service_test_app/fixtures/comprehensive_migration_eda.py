from service_test_app.models import Organization, Team, User


def setup():
    """Create test data for comprehensive EDA migration tests - AAP-47840 manual test scenarios."""

    # Create organizations
    test_org = Organization.objects.create(name="TestOrganization")
    eda_org = Organization.objects.create(name="EDAOrganization")

    # Create teams
    test_team = Team.objects.create(name="TestTeam", organization=test_org)
    eda_team = Team.objects.create(name="EDATeam", organization=eda_org)

    # Create admin user (required for migration)
    admin_user = User.objects.create(username="admin", is_superuser=True)
    admin_user.set_password("eda_admin_pass")
    admin_user.save()
    admin_user.organizations.set([eda_org])

    # === Test Case 3: User in Hub and EDA ===
    hub_eda_user = User.objects.create(username="hub-eda-user", email="hubeda@example.com", password="password123", first_name="HubEda", last_name="User")
    hub_eda_user.organizations.set([eda_org])
    hub_eda_user.teams.set([eda_team])

    # === Test Case 4: User in all services ===
    all_services_user = User.objects.create(
        username="all-services-user", email="allservices@example.com", password="password123", first_name="AllServices", last_name="User"
    )
    all_services_user.organizations.set([test_org])
    all_services_user.teams.set([test_team])
