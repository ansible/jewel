import pytest
from ansible_base.rbac.models import RoleDefinition, RoleUserAssignment
from django.urls import reverse


@pytest.mark.django_db
def test_system_auditor_change(admin_api_client, user_api_client, user):
    assert RoleDefinition.objects.filter(name='System Auditor').exists()

    assert not system_auditor_qs(user.id).exists()

    for flag_enabled in [True, False]:
        user.is_system_auditor = flag_enabled
        user.save()
        assert system_auditor_qs(user.id).exists() is flag_enabled

    url = reverse('user-detail', kwargs={'pk': user.id})
    for flag_enabled in [True, False]:
        response = admin_api_client.patch(url, {'is_system_auditor': flag_enabled})
        assert response.status_code == 200

        assert system_auditor_qs(user.id).exists() is flag_enabled


def system_auditor_qs(user_id):
    return RoleUserAssignment.objects.filter(object_id=None, user_id=user_id, role_definition__name='System Auditor')
