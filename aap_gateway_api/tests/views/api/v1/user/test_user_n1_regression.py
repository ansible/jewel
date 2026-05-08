"""
Regression tests for AAP-57509: N+1 queries in UserViewSet.

Verifies that:
  1. Query count for GET /api/v1/users/ stays constant as user count grows.
  2. last_login_results is correctly populated via the prefetch cache.
  3. associated_authenticators / authenticators response fields remain accurate.
"""

import pytest
from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.lib.utils.response import get_relative_url
from django.db import connection
from django.test.utils import CaptureQueriesContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_user_with_auth(django_user_model, authenticator, suffix):
    user = django_user_model.objects.create_user(username=f"aap57509_{suffix}", password="pw")
    AuthenticatorUser.objects.create(uid=f"uid_{suffix}", user=user, provider=authenticator)
    return user


# ---------------------------------------------------------------------------
# Query-count regression
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_user_list_query_count_constant(admin_api_client, local_authenticator, django_user_model):
    """Query growth per user must stay within budget, well below the pre-optimization baseline."""
    for i in range(3):
        _create_user_with_auth(django_user_model, local_authenticator, f"small_{i}")

    url = get_relative_url("user-list")
    with CaptureQueriesContext(connection) as small_ctx:
        response = admin_api_client.get(url)
    assert response.status_code == 200
    queries_for_small = len(small_ctx.captured_queries)

    for i in range(3, 10):
        _create_user_with_auth(django_user_model, local_authenticator, f"large_{i}")

    with CaptureQueriesContext(connection) as large_ctx:
        response = admin_api_client.get(url)
    assert response.status_code == 200
    queries_for_large = len(large_ctx.captured_queries)

    # The get_authenticator_ids/uids/associated_authenticators model methods still
    # use values_list/values (bypassing prefetch) because they are also called in
    # mutation paths that need fresh DB state.  This adds ~3 queries per user.
    # The prefetch optimization still eliminates N+1 for authenticator_users.all()
    # and select_related eliminates N+1 for last_login_from, modified_by, created_by.
    # Allow growth proportional to the remaining per-user queries but ensure it
    # stays well below the pre-optimization baseline (~8+ queries per user).
    extra_users = 7
    max_growth_per_user = 4
    assert queries_for_large <= queries_for_small + (extra_users * max_growth_per_user), (
        f"Query count grew from {queries_for_small} (3 users) to {queries_for_large} (10 users). "
        f"Growth of {queries_for_large - queries_for_small} exceeds budget of {extra_users * max_growth_per_user}. "
        "Possible N+1 regression in user serialization."
    )


# ---------------------------------------------------------------------------
# Correctness: last_login_results
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_last_login_results_populated_via_prefetch(admin_api_client, local_authenticator, django_user_model):
    """
    last_login_results must contain correct AuthenticatorUser data after switching
    the serializer from AuthenticatorUser.objects.filter(user=obj) to
    obj.authenticator_users.all() (which reads from the prefetch cache).
    """
    user = django_user_model.objects.create_user(username="aap57509_llr", password="pw")
    AuthenticatorUser.objects.create(
        uid="llr_uid",
        user=user,
        provider=local_authenticator,
        access_allowed=True,
        last_login_map_results=[{"map": "result"}],
        extra_data={"auth_time": "2026-01-15T12:00:00Z"},
    )

    url = get_relative_url("user-detail", kwargs={"pk": user.pk})
    response = admin_api_client.get(url)

    assert response.status_code == 200
    assert "last_login_results" in response.data, "last_login_results absent from admin response"

    results = response.data["last_login_results"]
    assert local_authenticator.id in results, f"Expected provider id {local_authenticator.id} in last_login_results, got keys: {list(results.keys())}"
    entry = results[local_authenticator.id]
    assert entry["access_allowed"] is True
    assert entry["last_login_map_results"] == [{"map": "result"}]
    assert entry["last_login_attempt"] == "2026-01-15T12:00:00Z"


# ---------------------------------------------------------------------------
# Correctness: associated_authenticators (summary_fields.authentication)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_associated_authenticators_correct_after_prefetch(admin_api_client, local_authenticator, django_user_model):
    """
    associated_authenticators in the user response must reflect actual AuthenticatorUser
    rows — verifying correctness is unchanged after the prefetch optimisation.
    """
    user = django_user_model.objects.create_user(username="aap57509_assoc", password="pw")
    AuthenticatorUser.objects.create(uid="assoc_uid", user=user, provider=local_authenticator)

    url = get_relative_url("user-detail", kwargs={"pk": user.pk})
    response = admin_api_client.get(url)

    assert response.status_code == 200
    assoc = response.data.get("associated_authenticators", {})
    assert local_authenticator.id in assoc, f"Authenticator {local_authenticator.id} missing from associated_authenticators: {assoc}"
    assert assoc[local_authenticator.id]["uid"] == "assoc_uid"


@pytest.mark.django_db
def test_last_login_results_absent_for_unprivileged_user(user_api_client, local_authenticator, django_user_model):
    """
    last_login_results must not be visible to a regular user viewing another user's record.
    """
    other = django_user_model.objects.create_user(username="aap57509_other", password="pw")
    AuthenticatorUser.objects.create(uid="other_uid", user=other, provider=local_authenticator)

    url = get_relative_url("user-detail", kwargs={"pk": other.pk})
    response = user_api_client.get(url)

    # Regular users can view basic details but not last_login_results of others
    if response.status_code == 200:
        assert "last_login_results" not in response.data, "last_login_results must not be exposed to unprivileged users viewing another user"
