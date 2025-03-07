from ansible_base.authentication.models import Authenticator
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.oauth2_provider.models import OAuth2Application
from django.test import TestCase
from rest_framework.test import APIClient

from aap_gateway_api.models import Organization, User

# Testing with fixtures and parameterization was taking a long time to execute
# that code is located in this drive link:
# https://drive.google.com/file/d/1XcIZsKI7buYnbTmqKNYBdYEb-8J8dA7g/view?usp=sharing


def mk_app(
    name="Test OAuth2 Application",
    description="Created for testing app_url API endpoint.",
    organization=None,
    app_url=None,
    redirect_uris="https://localhost/test_app",
    authorization_grant_type='authorization-code',
    client_type='confidential',
):
    the_oauth_app = OAuth2Application.objects.create(
        name=name,
        description=description,
        organization=organization,
        app_url=app_url,
        redirect_uris=redirect_uris,
        authorization_grant_type=authorization_grant_type,
        client_type=client_type,
    )
    return the_oauth_app


def quick_mk_user(username):
    user = User.objects.create(username=username, password="password", is_superuser=False, first_name='', last_name='', email='')
    return user


class AppUrlTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):

        Authenticator.objects.create(
            name="Test Local Authenticator",
            enabled=True,
            create_objects=True,
            remove_users=False,
            type="ansible_base.authentication.authenticator_plugins.local",
            configuration={},
        )

        # Create Orgs
        for i in range(7):
            Organization.objects.create(name=f"Org {i + 1}", description="")

        # Add 28 OAuth Applications:
        # Add  4 to 'Default' - two have app_url, one as Null, one as ''
        # Add  2 to 'Org 1'   - two have app_url
        # Add  2 to 'Org 2'   - one has app_url, one as Null
        # Add  2 to 'Org 3'   - one as Null, one as ''
        # Add  2 to 'Org 4'   - one has app_url, one as ''
        # Add 15 to 'Org 5'   - all have app_url
        # Add  1 to 'Org 6'   - matches the name and url from org 4
        current_organization = Organization.objects.get(name="Default")
        mk_app(organization=current_organization, name="Test OAuth2 App Default-1", app_url="https://localhost/Default-1")
        mk_app(organization=current_organization, name="Test OAuth2 App Default-2", app_url="https://localhost/Default-2")
        mk_app(organization=current_organization, name="Test OAuth2 App Default-Null-AppUrl-1")
        mk_app(organization=current_organization, name="Test OAuth2 App Default-Blank-AppUrl-1", app_url="")

        current_organization = Organization.objects.get(name="Org 1")
        mk_app(organization=current_organization, name="Test OAuth2 App Org1-1", app_url="https://localhost/Org1-1")
        mk_app(organization=current_organization, name="Test OAuth2 App Org1-2", app_url="https://localhost/Org1-2")

        current_organization = Organization.objects.get(name="Org 2")
        mk_app(organization=current_organization, name="Test OAuth2 App Org2-1", app_url="https://localhost/Org2-1")
        mk_app(organization=current_organization, name="Test OAuth2 App Org2-Null-AppUrl-1")

        current_organization = Organization.objects.get(name="Org 3")
        mk_app(organization=current_organization, name="Test OAuth2 App Org3-Null-AppUrl-1")
        mk_app(organization=current_organization, name="Test OAuth2 App Org3-Blank-AppUrl-1", app_url="")

        current_organization = Organization.objects.get(name="Org 4")
        mk_app(organization=current_organization, name="Test OAuth2 App Org1-1", app_url="https://localhost/Org1-1")
        mk_app(organization=current_organization, name="Test OAuth2 App Org4-Blank-AppUrl-1", app_url="")

        current_organization = Organization.objects.get(name="Org 5")
        for i in range(15):
            mk_app(organization=current_organization, name=f"Test OAuth2 App Org5-{i + 1}", app_url=f"https://localhost/Org5-{i}")

        # Deliberatley match the name from Org4's test!
        current_organization = Organization.objects.get(name="Org 6")

        mk_app(
            organization=current_organization,
            name="Test OAuth2 App Org4-1",
            app_url="https://localhost/Org4-1",
            description="Deliberately Matching one of the Name's and URL from the App from Org 1",
        )

        my_user_prefix = "AppUrlTestUser"

        User.objects.create(username=f"{my_user_prefix}-PlatformAdmin-NoOrg", password="password", is_superuser=True)
        User.objects.create(username=f"{my_user_prefix}-PlatformAuditor-NoOrg", password="password", is_superuser=False, is_platform_auditor=True)
        quick_mk_user(f"{my_user_prefix}-Normal-NoOrg")

        # We want some simple users to test with
        the_org_list = ["Default", "Org 1", "Org 2", "Org 3", "Org 4", "Org 5", "Org 6"]

        for user_type in ["Member", "Admin"]:
            for org in the_org_list:
                user = quick_mk_user(f"{my_user_prefix}-{user_type}-{org.replace(' ', '')}")
                the_org = Organization.objects.get(name=org)
                if user_type == "Admin":
                    the_org.add_admin(user)
                else:
                    the_org.add_member(user)

        # We want some complex users to test with (these users span orgs) - membership only, no org admin testing here
        the_complex_org_list = [
            ["Org 1", "Org 3"],
            ["Org 1", "Org 4"],
            ["Org 2", "Org 3"],
            ["Org 2", "Org 4"],
            ["Org 3", "Org 4"],
            ["Org 4", "Org 6"],
            ["Default", "Org 4", "Org 6"],
            ["Default", "Org 1", "Org 4"],
        ]
        for orgs in the_complex_org_list:
            user = quick_mk_user(f"{my_user_prefix}-{'-'.join(orgs).replace(' ', '')}")
            for org in orgs:
                Organization.objects.get(name=org).add_member(user)

    def execute_scenario(self, the_user, expected_count):
        url = get_relative_url("app_url-list")
        client = APIClient()
        assert client.login(username=the_user, password="password")
        response = client.get(url)

        assert response is not None and response.status_code == 200
        assert response.data is not None and 'count' in response.data
        assert response.data['count'] == expected_count

        try:
            client.logout()
        except AttributeError:
            # The test might have logged the user out already (e.g. to test the logout signal)
            pass

    def test_app_url_list_platform_admin(self):
        self.execute_scenario("AppUrlTestUser-PlatformAdmin-NoOrg", 22)

    def test_app_url_list_platform_auditor(self):
        self.execute_scenario("AppUrlTestUser-PlatformAuditor-NoOrg", 22)

    def test_app_url_list_user_no_org(self):
        self.execute_scenario("AppUrlTestUser-Normal-NoOrg", 0)

    def test_app_url_list_org_admin_org_1(self):
        self.execute_scenario("AppUrlTestUser-Admin-Org1", 2)

    def test_app_url_list_user_org_1(self):
        self.execute_scenario("AppUrlTestUser-Member-Org1", 2)

    def test_app_url_list_org_admin_org_2(self):
        self.execute_scenario("AppUrlTestUser-Admin-Org2", 1)

    def test_app_url_list_user_org_2(self):
        self.execute_scenario("AppUrlTestUser-Member-Org2", 1)

    def test_app_url_list_org_admin_org_3(self):
        self.execute_scenario("AppUrlTestUser-Admin-Org3", 0)

    def test_app_url_list_user_org_3(self):
        self.execute_scenario("AppUrlTestUser-Member-Org3", 0)

    def test_app_url_list_org_admin_org_4(self):
        self.execute_scenario("AppUrlTestUser-Admin-Org4", 1)

    def test_app_url_list_user_org_4(self):
        self.execute_scenario("AppUrlTestUser-Member-Org4", 1)

    def test_app_url_list_org_admin_org_5(self):
        self.execute_scenario("AppUrlTestUser-Admin-Org5", 15)

    def test_app_url_list_user_org_5(self):
        self.execute_scenario("AppUrlTestUser-Member-Org5", 15)

    def test_app_url_list_org_admin_org_6(self):
        self.execute_scenario("AppUrlTestUser-Admin-Org6", 1)

    def test_app_url_list_user_org_6(self):
        self.execute_scenario("AppUrlTestUser-Member-Org6", 1)

    def test_app_url_list_user_org_1_org_3(self):
        self.execute_scenario("AppUrlTestUser-Org1-Org3", 2)

    def test_app_url_list_user_org_1_org_4(self):
        self.execute_scenario("AppUrlTestUser-Org1-Org4", 3)

    def test_app_url_list_user_org_2_org_3(self):
        self.execute_scenario("AppUrlTestUser-Org2-Org3", 1)

    def test_app_url_list_user_org_2_org_4(self):
        self.execute_scenario("AppUrlTestUser-Org2-Org4", 2)

    def test_app_url_list_user_org_3_org_4(self):
        self.execute_scenario("AppUrlTestUser-Org3-Org4", 1)

    def test_app_url_list_user_org_4_org_6(self):
        self.execute_scenario("AppUrlTestUser-Org4-Org6", 2)

    def test_app_url_list_user_default_org_4_org_6(self):
        self.execute_scenario("AppUrlTestUser-Default-Org4-Org6", 4)

    def test_app_url_list_user_default_org_1_org_4(self):
        self.execute_scenario("AppUrlTestUser-Default-Org1-Org4", 5)
