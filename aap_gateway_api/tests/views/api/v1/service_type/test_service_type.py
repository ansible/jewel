from unittest import mock

from ansible_base.lib.utils.response import get_relative_url

from aap_gateway_api.models import DefaultServiceType, ServiceCluster, ServiceType


def test_service_type_detail_controller(admin_api_client, service_type_controller):
    url = get_relative_url("service_type-detail", kwargs={"pk": service_type_controller.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data["name"] == "controller"
    assert response.data["id"] == service_type_controller.pk
    assert response.data["ping_url"] == "/api/v2/ping/"


def test_service_type_list(admin_api_client, request):
    url = get_relative_url("service_type-list")
    response = admin_api_client.get(url)
    assert response.status_code == 200
    st_count = len(response.data["results"])
    assert st_count >= len(DefaultServiceType)  # There can be more than the core services

    found_types = {}
    for t in response.data["results"]:
        found_types[t["name"]] = t["id"]

    for fixture in request.fixturenames:
        if fixture.startswith('service_type'):
            # Find all service_type_<whatever> fixtures and make sure we find an entry for
            # each one (matching <whatever> portion above)
            fixture_type = fixture.split('_')[-1]
            assert fixture_type in found_types
            assert request.getfixturevalue(fixture).pk == found_types[fixture_type]


def test_service_type_create(admin_api_client):
    url = get_relative_url("service_type-list")
    response = admin_api_client.post(url, {"name": "My New Service Type", "ping_url": "/ping/"})
    assert response.status_code == 201
    assert response.data["name"] == "My New Service Type"
    assert response.data["id"] > 3
    assert ServiceType.objects.filter(pk=response.data["id"]).exists()
    assert ServiceType.objects.filter(pk=response.data["id"]).first().ping_url == "/ping/"


def test_service_type_update(admin_api_client, service_type_controller):
    url = get_relative_url("service_type-detail", kwargs={"pk": service_type_controller.pk})
    response = admin_api_client.patch(url, {"name": "My Hub"})
    assert response.status_code == 200
    assert response.data["id"] == service_type_controller.pk
    assert ServiceType.objects.filter(pk=response.data["id"], name="My Hub").exists()


def test_service_type_update_proxy(admin_api_client):
    # Ensure default not editable via proxy
    for type in DefaultServiceType:
        st = ServiceType.objects.filter(name=type.value).first()
        url = get_relative_url("service_type-detail", kwargs={"pk": st.pk})
        with mock.patch('aap_gateway_api.utils.views.permissions.from_proxy', return_value=True):
            response = admin_api_client.patch(url, {"name": "changed"})
        assert response.status_code == 403, 'Mod of default service type should fail'

        st = ServiceType.objects.filter(id=st.pk).first()
        assert st.name != "changed", 'Default service types should not be changable'

    # Ensure non-default editable via proxy
    url = get_relative_url("service_type-list")
    response = admin_api_client.post(url, {"name": "newbie", "ping_url": "/ping/"})
    st = ServiceType.objects.filter(name="newbie").first()
    url = get_relative_url("service_type-detail", kwargs={"pk": st.pk})
    with mock.patch('aap_gateway_api.utils.views.permissions.from_proxy', return_value=True):
        response = admin_api_client.patch(url, {"name": "changed"})
    assert response.status_code == 200, 'Mod of non-default servie type should be accepted'
    st = ServiceType.objects.filter(name="changed").first()
    assert st, "Could not find expected 'changed' service type"


def test_service_type_delete(admin_api_client, service_type_controller):
    url = get_relative_url("service_type-detail", kwargs={"pk": service_type_controller.pk})
    response = admin_api_client.delete(url)
    assert response.status_code == 204
    assert not ServiceType.objects.filter(pk=service_type_controller.pk).exists()
    assert ServiceCluster.get_cluster_by_type(service_type=service_type_controller.pk) is None


def test_service_type_delete_proxy(admin_api_client):
    # Ensure default not deletable via proxy
    for type in DefaultServiceType:
        st = ServiceType.objects.filter(name=type.value).first()
        url = get_relative_url("service_type-detail", kwargs={"pk": st.pk})
        with mock.patch('aap_gateway_api.utils.views.permissions.from_proxy', return_value=True):
            response = admin_api_client.delete(url)
        assert response.status_code == 403, 'Deletion of default service type should fail'

        st = ServiceType.objects.filter(id=st.pk).first()
        assert st, 'Default service types should not be deletable'

    # Ensure non-default deletable via proxy
    url = get_relative_url("service_type-list")
    response = admin_api_client.post(url, {"name": "newbie", "ping_url": "/ping/"})
    st = ServiceType.objects.filter(name="newbie").first()
    url = get_relative_url("service_type-detail", kwargs={"pk": st.pk})
    with mock.patch('aap_gateway_api.utils.views.permissions.from_proxy', return_value=True):
        response = admin_api_client.delete(url)
    assert response.status_code == 204, 'Deletion of non-default servie type should be accepted'
    st = ServiceType.objects.filter(name="newbie").first()
    assert st is None, "Non-default service type should be deletable"


def test_service_type_name_must_be_unique(admin_api_client, service_type_controller):
    url = get_relative_url('service_type-list')
    data = {'name': service_type_controller.name, 'ping_url': '/ping/'}
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 400
    assert response.data['name'][0].code == 'unique'


def test_service_type_create_with_missing_name(admin_api_client):
    url = get_relative_url("service_type-list")
    response = admin_api_client.post(url, {'ping_url': '/ping/'})
    assert response.status_code == 400
    assert response.data["name"][0] == "This field is required."
    assert not ServiceType.objects.filter(name='').exists()
