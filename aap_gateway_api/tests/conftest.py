import pytest
import uuid


@pytest.fixture
def unauthenticated_api_client(db):
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def admin_api_client(db, admin_user, unauthenticated_api_client):
    client = unauthenticated_api_client
    client.force_authenticate(user=admin_user)
    yield client
    client.force_authenticate(user=None)


@pytest.fixture
def environment():
    from aap_gateway_api.models import Environment

    random_name = f"Test Environment {uuid.uuid4().hex[:6]}"
    environment = Environment.objects.create(name=random_name)
    yield environment
    environment.delete()
