import pytest
from django.urls import reverse

from aap_gateway_api.tests.functional.rbac.conftest import TestPermissionsBase


@pytest.mark.django_db
class TestActivityStreamPermissions(TestPermissionsBase):
    def test_activity_stream_list(self, user_type, user):
        url = reverse("activitystream-list")
        response = self.api_client.get(url)

        if user_type == 'unauthenticated':
            assert response.status_code == 401
        elif user_type == 'user':
            assert response.status_code == 403
        else:
            assert response.status_code == 200
            assert response.data['count'] > 0  # Some data created by user creation

    def test_activity_stream_detail(self, user_type, user):
        last_entry = user.activity_stream_entries.last()

        url = reverse("activitystream-detail", kwargs={"pk": last_entry.id})
        response = self.api_client.get(url)

        if user_type == 'unauthenticated':
            assert response.status_code == 401
        elif user_type == 'user':
            assert response.status_code == 403
        else:
            assert response.status_code == 200
            assert response.data['id'] == last_entry.id

    def test_activity_stream_create(self, user_type, user):
        last_entry = user.activity_stream_entries.last()
        data = {
            "content_type": last_entry.content_type,
            "object_id": last_entry.object_id,
            "content_object": last_entry.content_object,
            "operation": 'delete',
        }

        url = reverse("activitystream-list")
        response = self.api_client.post(url, data)

        if user_type == 'unauthenticated':
            assert response.status_code == 401
        elif user_type in ['user', 'system_auditor']:
            assert response.status_code == 403
        else:
            assert response.status_code == 405

    def test_activity_stream_update(self, user_type, user):
        last_entry = user.activity_stream_entries.last()
        data = {
            "content_type": last_entry.content_type,
            "object_id": last_entry.object_id,
            "content_object": last_entry.content_object,
            "operation": 'delete',
        }

        url = reverse("activitystream-detail", kwargs={"pk": last_entry.id})
        response = self.api_client.put(url, data)

        if user_type == 'unauthenticated':
            assert response.status_code == 401
        elif user_type in ['user', 'system_auditor']:
            assert response.status_code == 403
        else:
            assert response.status_code == 405

    def test_activity_stream_delete(self, user_type, user):
        last_entry = user.activity_stream_entries.last()

        url = reverse("activitystream-detail", kwargs={"pk": last_entry.id})
        response = self.api_client.delete(url)

        if user_type == 'unauthenticated':
            assert response.status_code == 401
        elif user_type in ['user', 'system_auditor']:
            assert response.status_code == 403
        else:
            assert response.status_code == 405
