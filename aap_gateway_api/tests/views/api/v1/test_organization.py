from ansible_base.lib.utils.response import get_relative_url

from aap_gateway_api.models import Organization


def test_prevent_deletion_of_managed_organization(admin_api_client):
    org = Organization.objects.create(name="TestOrg", managed=True)
    org.refresh_from_db()
    assert org.managed is True
    url = get_relative_url("organization-detail", kwargs={"pk": org.pk})
    response = admin_api_client.delete(url)
    assert response.status_code == 400
    assert response.data["details"] == "Managed organizations cannot be deleted."
