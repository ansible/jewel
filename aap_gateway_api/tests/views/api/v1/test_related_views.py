import pytest
from rest_framework.reverse import reverse


class TestRelatedViews:
    @pytest.mark.parametrize(
        "view_name",
        [
            ('user-teams-list'),
            ('user-organizations-list'),
        ],
    )
    def test_user_team_view(self, view_name, admin_api_client, admin_user):
        url = reverse(view_name, kwargs={'pk': admin_user.id})
        response = admin_api_client.get(url)
        assert response.status_code == 200

    @pytest.mark.parametrize(
        "view_name",
        [
            ('user-teams-list'),
            ('user-organizations-list'),
        ],
    )
    def test_user_team_view_invalid_user_id(self, view_name, admin_api_client):
        url = reverse(view_name, kwargs={'pk': 27})
        response = admin_api_client.get(url)
        assert response.status_code == 404
