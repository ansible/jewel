import pytest
from django.urls import reverse


@pytest.mark.parametrize("view_name", [('user-authorized-tokens-list'), ('user-personal-tokens-list')])
def test_ensure_oauth2_tokens_in_user_view(view_name, system_user):
    reverse(view_name, kwargs={'pk': system_user.pk})
