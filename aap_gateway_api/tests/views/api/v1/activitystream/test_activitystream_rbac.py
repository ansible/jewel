import pytest
from ansible_base.lib.utils.response import get_relative_url

from aap_gateway_api.tests.views.api.v1.conftest import TestPermissionsBase


@pytest.mark.django_db
class TestActivityStreamPermissions(TestPermissionsBase):
    def test_activity_stream_list(self, user_type, user):
        url = get_relative_url("activitystream-list")
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

        url = get_relative_url("activitystream-detail", kwargs={"pk": last_entry.id})
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

        url = get_relative_url("activitystream-list")
        response = self.api_client.post(url, data)

        if user_type == 'unauthenticated':
            assert response.status_code == 401
        elif user_type in ['user', 'platform_auditor']:
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

        url = get_relative_url("activitystream-detail", kwargs={"pk": last_entry.id})
        response = self.api_client.put(url, data)

        if user_type == 'unauthenticated':
            assert response.status_code == 401
        elif user_type in ['user', 'platform_auditor']:
            assert response.status_code == 403
        else:
            assert response.status_code == 405

    def test_activity_stream_delete(self, user_type, user):
        last_entry = user.activity_stream_entries.last()

        url = get_relative_url("activitystream-detail", kwargs={"pk": last_entry.id})
        response = self.api_client.delete(url)

        if user_type == 'unauthenticated':
            assert response.status_code == 401
        elif user_type in ['user', 'platform_auditor']:
            assert response.status_code == 403
        else:
            assert response.status_code == 405
