"""Performance and scaling tests for RoleAssignmentsMixin.

These tests verify that the bulk migration code scales correctly:
- Query count is O(pages), not O(items)
- Memory stays bounded by page size, not total record count
"""

import tracemalloc
from unittest.mock import Mock

import pytest
from ansible_base.rbac.models import RoleDefinition

from aap_gateway_api.management.commands._migrate_service_data.cursor_store import CursorStore
from aap_gateway_api.management.commands.migrate_service_data import Command as MigrateCommand


def _make_remote_assignment(
    assignment_type,
    actor_ansible_id,
    role_name,
    pk=None,
    content_type=None,
    object_ansible_id=None,
    object_id=None,
):
    """Build a dict matching the service API assignment response format."""
    d = {
        f"{assignment_type}_ansible_id": actor_ansible_id,
        "role_definition": role_name,
        "content_type": content_type or "",
        "object_ansible_id": object_ansible_id,
        "object_id": object_id,
    }
    if pk is not None:
        d["id"] = pk
    return d


def _make_cmd():
    cmd = MigrateCommand()
    cmd.stdout = Mock()
    cmd.stderr = Mock()
    return cmd


def _create_test_data(user_count, org_count):
    """Create users and orgs for scaling tests. Returns (users, orgs, role_definition)."""
    from django.contrib.auth import get_user_model

    from aap_gateway_api.models import Organization

    User = get_user_model()

    users = [User.objects.create(username=f"perf-user-{i:04d}") for i in range(user_count)]
    orgs = [Organization.objects.create(name=f"perf-org-{i:04d}") for i in range(org_count)]

    from ansible_base.rbac.models import DABContentType

    org_ct = DABContentType.objects.get_for_model(Organization)
    rd, _ = RoleDefinition.objects.get_or_create(
        name="Organization Admin",
        defaults={"managed": True, "content_type": org_ct},
    )

    return users, orgs, rd


def _build_assignments(users, orgs, count):
    """Build mock assignment results distributing users across orgs."""
    results = []
    for i in range(count):
        user = users[i % len(users)]
        org = orgs[i % len(orgs)]
        results.append(
            _make_remote_assignment(
                "user",
                str(user.resource.ansible_id),
                "Organization Admin",
                pk=i + 1,
                content_type="shared.organization",
                object_ansible_id=str(org.resource.ansible_id),
            )
        )
    return results


# =============================================================================
# Query count — absolute bound per page
# =============================================================================


@pytest.mark.django_db
def test_bulk_resolve_query_count_bounded_per_page():
    """Verify that _bulk_resolve_and_create_page uses a fixed number of DB
    queries regardless of how many assignments are on the page.

    With 200 assignments, the old per-assignment approach would use 600+
    queries (3+ per assignment).  The bulk approach should use ~6 queries:
      1. RoleDefinition lookup
      2. Resource lookup (actors)
      3. Resource lookup (objects)
      4. ObjectRole bulk_create
      5. ObjectRole fetch
      6. RoleUserAssignment bulk_create
    """
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    cmd = _make_cmd()
    users, orgs, _ = _create_test_data(user_count=200, org_count=10)
    results = _build_assignments(users, orgs, 200)

    with CaptureQueriesContext(connection) as ctx:
        created, object_roles = cmd._bulk_resolve_and_create_page(results, "user")

    assert created == 200
    assert len(object_roles) > 0
    assert len(ctx.captured_queries) < 20, (
        f"Expected fewer than 20 queries for 200 assignments, got {len(ctx.captured_queries)}. Queries: {[q['sql'][:80] for q in ctx.captured_queries]}"
    )


# =============================================================================
# Query count — O(1) per page, not O(items)
# =============================================================================


@pytest.mark.django_db
def test_query_count_scales_with_pages_not_items():
    """Doubling items on a page should NOT double queries.

    Runs _bulk_resolve_and_create_page at two scales and asserts the
    query-count ratio stays near 1.0, proving O(pages) not O(items).
    """
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    users, orgs, _ = _create_test_data(user_count=400, org_count=20)

    def _count_queries(n_items):
        cmd = _make_cmd()
        results = _build_assignments(users, orgs, n_items)
        with CaptureQueriesContext(connection) as ctx:
            cmd._bulk_resolve_and_create_page(results, "user")
        return len(ctx.captured_queries)

    queries_100 = _count_queries(100)
    queries_400 = _count_queries(400)

    ratio = queries_400 / max(queries_100, 1)
    assert ratio < 1.5, (
        f"Query count scaled {ratio:.1f}x for 4x items — expected ~1x (O(1) per page). 100 items: {queries_100} queries, 400 items: {queries_400} queries"
    )


# =============================================================================
# Memory — bounded by page size, not total record count
# =============================================================================


def _measure_pagination_memory(users, orgs, num_assignments, page_size=50):
    """Run _paginate_and_create and return peak memory delta in bytes."""
    cmd = _make_cmd()
    cmd.BIG_PAGE_FILTERS = {"page_size": str(page_size)}

    all_results = _build_assignments(users, orgs, num_assignments)
    pages = [all_results[i : i + page_size] for i in range(0, len(all_results), page_size)]

    page_iter = iter(pages)

    def fake_list(filters=None):
        try:
            page = next(page_iter)
        except StopIteration:
            page = []
        resp = Mock(status_code=200)
        resp.json.return_value = {"results": page, "count": num_assignments}
        return resp

    cursor = CursorStore("perf-test", "user", log_fn=cmd._log)

    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()

    cmd._paginate_and_create(fake_list, "user", [], cursor)

    snapshot_after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    stats = snapshot_after.compare_to(snapshot_before, "lineno")
    return sum(s.size_diff for s in stats if s.size_diff > 0)


@pytest.mark.django_db
def test_pagination_memory_scales_with_page_size_not_total():
    """Memory during pagination should stay proportional to page size,
    not grow with total record count.

    Runs at two scales (500 vs 2000 total assignments, same page size)
    and asserts the memory ratio stays well below the data ratio.
    A load-everything regression would show ~4x memory growth.
    """
    users, orgs, _ = _create_test_data(user_count=500, org_count=20)

    mem_500 = _measure_pagination_memory(users, orgs, num_assignments=500)
    mem_2000 = _measure_pagination_memory(users, orgs, num_assignments=2000)

    ratio = mem_2000 / max(mem_500, 1)
    assert ratio < 2.5, (
        f"Memory scaled {ratio:.1f}x for 4x data — expected ~1x (bounded by page size). 500 items: {mem_500:,} bytes, 2000 items: {mem_2000:,} bytes"
    )
