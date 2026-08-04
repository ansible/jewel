"""Perf tests for organization delete scaling.

Detects O(n) regressions in org delete by comparing wall-clock time at
two team counts. With RBAC deferral active, delete time should be
roughly constant regardless of team count. Without deferral, it scales
linearly (each team triggers a full RBAC recomputation).
"""

import time

import pytest
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import RoleDefinition

from aap_gateway_api.models import Organization, Team, User


def _create_org_with_teams(name_prefix, num_teams, users_per_team):
    """Create an org with teams and user role assignments."""
    org = Organization.objects.create(name=f"{name_prefix}-org")
    team_member_rd = RoleDefinition.objects.get(name="Team Member")
    org_member_rd = RoleDefinition.objects.get(name="Organization Member")

    users = []
    for i in range(num_teams):
        team = Team.objects.create(name=f"{name_prefix}-team-{i}", organization=org)
        for j in range(users_per_team):
            user = User.objects.create_user(
                username=f"{name_prefix}-user-{i}-{j}",
                password="PerfTest1234!",
            )
            users.append(user)
            org_member_rd.give_permission(user, org)
            team_member_rd.give_permission(user, team)

    return org, users


def _time_api_delete(client, org):
    """Delete an org via the API and return wall-clock seconds."""
    url = get_relative_url("organization-detail", kwargs={"pk": org.pk})
    start = time.monotonic()
    response = client.delete(url)
    elapsed = time.monotonic() - start
    assert response.status_code == 204, f"Delete failed with {response.status_code}"
    return elapsed


@pytest.mark.django_db(transaction=True)
def test_org_delete_time_scales_sublinearly(admin_api_client, local_authenticator):
    """Org delete with 20 teams should take less than 3x the time of 5 teams.

    With RBAC deferral (defer_rbac_computations), all per-team signal
    work is batched into a single flush, making delete time roughly O(1).
    Without deferral, each team triggers a full recomputation and delete
    time scales linearly — 4x teams would take ~4x longer.

    The 3x threshold allows for DB overhead that grows slightly with more
    rows to cascade-delete, while catching true O(n) regressions where
    the ratio would be > 4x.
    """
    time_small = _time_api_delete(
        admin_api_client,
        _create_org_with_teams("perf-small", num_teams=5, users_per_team=3)[0],
    )

    time_large = _time_api_delete(
        admin_api_client,
        _create_org_with_teams("perf-large", num_teams=20, users_per_team=3)[0],
    )

    ratio = time_large / max(time_small, 0.01)
    assert ratio < 3.0, (
        f"Org delete is scaling linearly: {time_small:.2f}s (5 teams) vs "
        f"{time_large:.2f}s (20 teams), ratio {ratio:.1f}x. "
        f"Expected < 3.0x with RBAC deferral active."
    )
