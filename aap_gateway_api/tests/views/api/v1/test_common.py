import pytest
from django.urls import reverse
from oauthlib.common import generate_token


@pytest.mark.django_db
@pytest.mark.parametrize(
    'token, expected',
    [
        ('fixture', 200),
        ('bad', 401),
    ],
)
def test_ensure_oauth2_application_tokens_authenticate(token, expected, oauth2_admin_access_token, admin_user, unauthenticated_api_client):
    url = reverse("user-detail", kwargs={"pk": admin_user.pk})
    token = oauth2_admin_access_token.token if token == 'fixture' else generate_token()
    response = unauthenticated_api_client.get(
        url,
        headers={'Authorization': f'Bearer {token}'},
    )
    assert response.status_code == expected
    if expected != 401:
        assert response.data['username'] == admin_user.username
