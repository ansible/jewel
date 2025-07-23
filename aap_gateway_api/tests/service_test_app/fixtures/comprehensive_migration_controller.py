from service_test_app.models import Organization, Team, User


def setup():
    """Create test data for comprehensive Controller migration tests - AAP-47840 manual test scenarios."""

    # Create organizations
    test_org = Organization.objects.create(name="TestOrganization")
    default_org = Organization.objects.create(name="Default")

    # Create teams
    test_team = Team.objects.create(name="TestTeam", organization=test_org)
    admin_team = Team.objects.create(name="AdminTeam", organization=default_org)

    # Create admin user (required for migration)
    admin_user = User.objects.create(username="admin", is_superuser=True)
    admin_user.set_password("controller_admin_pass")
    admin_user.save()
    admin_user.organizations.set([default_org])
    admin_user.teams.set([admin_team])

    # === Test Case 1: User only in Controller ===
    controller_only_user = User.objects.create(
        username="controller-only-user", email="controller@example.com", password="password123", first_name="Controller", last_name="User"
    )
    controller_only_user.organizations.set([test_org])
    controller_only_user.teams.set([test_team])

    # === Test Case 2: User in Controller and Hub ===
    multi_service_user = User.objects.create(
        username="controller-hub-user", email="multi@example.com", password="password123", first_name="Multi", last_name="User"
    )
    multi_service_user.organizations.set([test_org])
    multi_service_user.teams.set([test_team])

    # === Test Case 4: User in all services ===
    all_services_user = User.objects.create(
        username="all-services-user", email="allservices@example.com", password="password123", first_name="AllServices", last_name="User"
    )
    all_services_user.organizations.set([test_org])
    all_services_user.teams.set([test_team])
