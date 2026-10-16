# Role Assignment Batch Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-assignment Gateway fan-out during authenticator-map reconciliation with generic, typed DAB batch grant/removal synchronization.

**Architecture:** DAB adds atomic typed bulk actions and generic service-index clients. Gateway accumulates claim-reconciliation changes, then sends at most one user grant batch and one user removal batch to each connected component through `AllServicesClient`.

**Tech Stack:** Django, Django REST Framework, django-ansible-base RBAC pipeline, pytest/tox, ATF.

**Spec:** `docs/superpowers/specs/2026-10-01-role-assignment-batch-sync-design.md`

## Global Constraints

- Preserve individual `assign` and `unassign` routes and clients unchanged.
- Keep user and team endpoints separate.
- Send `from_service` and optional `created_by_ansible_id` once in the batch wrapper.
- Validate all items before a mutation; malformed or unauthorized batches must be atomic.
- Keep Gateway login non-blocking and retain periodic sync as recovery.

## Review Focus

- Invalid second item rolls back a valid first item.
- Repeated grants/removals report idempotent existing/missing counts.
- Gateway system creators are omitted; common normal creators are lifted into the wrapper.
- Many grants and removals create two fan-outs, not one per assignment.
- Timeout, missing route, and non-2xx responses log without blocking login.

---

### Task 1: DAB batch wrapper serializers and resolution helpers

**Files:**
- Modify: `django-ansible-base/ansible_base/rbac/service_api/serializers.py:76-206`
- Test: `django-ansible-base/test_app/tests/rbac/remote/test_service_api.py`

**Produces:** typed wrappers with `from_service`, optional `created_by_ansible_id`, and a non-empty `assignments` list; a shared helper that resolves a validated item to `(role_definition, actor, content_object)`.

- [ ] **Step 1: Write failing serializer tests**

```python
def test_user_batch_rejects_empty_assignments():
    serializer = ServiceRoleUserAssignmentBatchSerializer(data={"assignments": []})
    assert not serializer.is_valid()
    assert "assignments" in serializer.errors


def test_user_batch_accepts_existing_item_schema(rando, inv_rd, inventory):
    serializer = ServiceRoleUserAssignmentBatchSerializer(data={
        "from_service": str(uuid4()),
        "assignments": [{"role_definition": inv_rd.name, "user_ansible_id": str(rando.resource.ansible_id), "object_id": str(inventory.pk)}],
    })
    assert serializer.is_valid(), serializer.errors
```

- [ ] **Step 2: Verify RED**

Run:

```bash
ANSIBLE_BASE_TEST_DIRS='test_app/tests/rbac/remote/test_service_api.py -k batch' tox -e py312
```

Expected: import failure because batch serializers do not exist.

- [ ] **Step 3: Implement minimal wrappers and extract existing item resolution**

```python
class BaseAssignmentBatchSerializer(serializers.Serializer):
    from_service = serializers.UUIDField()
    created_by_ansible_id = serializers.UUIDField(required=False, allow_null=True)
    assignments = serializers.ListField(child=serializers.DictField(), allow_empty=False)
```

Keep per-item fields in the existing user/team serializer. Factor the role, actor, content-object, RemoteObject-fallback, and permission-check logic out of `BaseAssignmentSerializer.create()` so the single and batch paths share it.

- [ ] **Step 4: Verify GREEN and commit**

```bash
ANSIBLE_BASE_TEST_DIRS='test_app/tests/rbac/remote/test_service_api.py -k batch' tox -e py312
git add ansible_base/rbac/service_api/serializers.py test_app/tests/rbac/remote/test_service_api.py
git commit -m "feat: add role assignment batch validation"
```

### Task 2: DAB atomic typed bulk actions

**Files:**
- Modify: `django-ansible-base/ansible_base/rbac/service_api/views.py:50-176`
- Test: `django-ansible-base/test_app/tests/rbac/remote/test_service_api.py`

**Produces:** `bulk-assign` and `bulk-unassign` actions on user/team viewsets. Grants return `{created, existing}`; removals return `{deleted, missing}`.

- [ ] **Step 1: Write failing endpoint tests**

```python
def test_bulk_assign_is_idempotent(admin_api_client, rando, inv_rd, inventory, organization):
    data = {"assignments": [
        {"role_definition": inv_rd.name, "user_ansible_id": str(rando.resource.ansible_id), "object_id": str(inventory.pk)},
        {"role_definition": inv_rd.name, "user_ansible_id": str(rando.resource.ansible_id), "object_id": str(organization.pk)},
    ]}
    url = get_relative_url("serviceuserassignment-bulk-assign")
    assert admin_api_client.post(url, data=data, format="json").data == {"created": 2, "existing": 0}
    assert admin_api_client.post(url, data=data, format="json").data == {"created": 0, "existing": 2}


def test_bulk_assign_is_atomic_when_one_item_is_invalid(admin_api_client, rando, inv_rd, inventory):
    response = admin_api_client.post(get_relative_url("serviceuserassignment-bulk-assign"), data={"assignments": [
        {"role_definition": inv_rd.name, "user_ansible_id": str(rando.resource.ansible_id), "object_id": str(inventory.pk)},
        {"role_definition": "does-not-exist", "user_ansible_id": str(rando.resource.ansible_id), "object_id": str(inventory.pk)},
    ]}, format="json")
    assert response.status_code == 400
    assert not RoleUserAssignment.objects.filter(user=rando, role_definition=inv_rd).exists()
```

Add equivalent team and removal/missing tests.

- [ ] **Step 2: Verify RED**

Run the Task 1 test command. Expected: route reverse failure or 404.

- [ ] **Step 3: Implement shared bulk view helpers**

Add `@action(detail=False, methods=['post'], url_path='bulk-assign')` and `bulk-unassign` to both viewsets. Copy wrapper metadata into each raw item, validate the list through `self.get_serializer(data=items, many=True)`, resolve every item before entering `transaction.atomic()`, then:

```python
# grants
existing = self._find_existing_batch(resolved_items)
created = bulk_give_permissions(user_permissions=user_triples, team_permissions=team_triples)
return Response({"created": len(created) - len(existing), "existing": len(existing)})

# removals
existing = self._find_existing_batch(resolved_items)
for assignment in existing:
    check_can_remove_assignment(request.user, assignment)
remove_assignments(user_assignments=user_existing, team_assignments=team_existing)
return Response({"deleted": len(existing), "missing": len(resolved_items) - len(existing)})
```

Invoke existing secondary-sync hooks only for changed records, passing wrapper `from_service`.

- [ ] **Step 4: Verify GREEN and commit**

```bash
ANSIBLE_BASE_TEST_DIRS='test_app/tests/rbac/remote/test_service_api.py' tox -e py312
git add ansible_base/rbac/service_api/views.py test_app/tests/rbac/remote/test_service_api.py
git commit -m "feat: add bulk service role assignment actions"
```

### Task 3: DAB generic batch client

**Files:**
- Modify: `django-ansible-base/ansible_base/resource_registry/rest_client.py:154-232`
- Test: `django-ansible-base/test_app/tests/resource_registry/test_resources_api_rest_client.py`

**Produces:** `sync_assignments(assignments)` and `sync_unassignments(operations)`, inherited by `AllServicesClient`.

- [ ] **Step 1: Write failing payload tests**

```python
def test_sync_assignments_lifts_common_metadata_once(resource_client, assignment):
    with patch.object(resource_client, "_make_request", return_value=MagicMock()) as request:
        resource_client.sync_assignments([assignment])
    _, url = request.call_args.args[:2]
    payload = request.call_args.kwargs["data"]
    assert url == "role-user-assignments/bulk-assign/"
    assert "from_service" in payload
    assert "from_service" not in payload["assignments"][0]
```

Add team-route, removal-route, normal-creator, and `_system`-creator omission cases.

- [ ] **Step 2: Verify RED, then implement grouping**

Run:

```bash
ANSIBLE_BASE_TEST_DIRS='test_app/tests/resource_registry/test_resources_api_rest_client.py -k sync_assignments' tox -e py312
```

Expected: `AttributeError` before implementation.

Serialize items with existing serializers, strip `from_service` and `created_by_ansible_id` from every item, group by user/team and creator, then post one wrapper per group to `role-{user|team}-assignments/bulk-{assign|unassign}/`. Omit the creator field for the local system user.

- [ ] **Step 3: Verify GREEN and commit**

```bash
ANSIBLE_BASE_TEST_DIRS='test_app/tests/resource_registry/test_resources_api_rest_client.py' tox -e py312
git add ansible_base/resource_registry/rest_client.py test_app/tests/resource_registry/test_resources_api_rest_client.py
git commit -m "feat: add bulk role assignment sync client"
```

### Task 4: Gateway reconciliation batch collection

**Files:**
- Modify: `aap_gateway_api/authentication/reconcile.py:10-37`
- Test: `aap_gateway_api/tests/authentication/test_authenticator_map_reconcile.py`

**Produces:** one post-reconciliation grant call and one removal call at most, each using `AllServicesClient(wait_for_response=False)`.

- [ ] **Step 1: Replace single-sync tests with failing batch tests**

```python
def test_multiple_authenticator_map_grants_sync_once(all_services_client):
    reconciler._pending_grants = [assignment_one, assignment_two]
    reconciler._flush_pending_sync()
    client = all_services_client.return_value.with_callback.return_value
    client.sync_assignments.assert_called_once_with([assignment_one, assignment_two])


def test_multiple_authenticator_map_removals_sync_once(all_services_client):
    reconciler._pending_removals = [(role_one, user, org_one), (role_two, user, org_two)]
    reconciler._flush_pending_sync()
    client = all_services_client.return_value.with_callback.return_value
    client.sync_unassignments.assert_called_once_with(reconciler._pending_removals)
```

Cover mixed operations, empty lists, no returned grant assignment, response `None`, and non-2xx logging.

- [ ] **Step 2: Verify RED, implement collection, then verify GREEN**

```bash
GATEWAY_TEST_DIRS='' PYTEST_NUM_PROCESSES=1 tox -e py312 -- aap_gateway_api/tests/authentication/test_authenticator_map_reconcile.py -v
```

Implement:

```python
def apply_permissions(self):
    self._pending_grants = []
    self._pending_removals = []
    super().apply_permissions()
    self._flush_pending_sync()
```

`_give_permission()` appends returned assignments; `_remove_permission()` saves `(role_definition, self.user, obj)` before delegating. `_flush_pending_sync()` creates no client for empty lists and uses operation-specific callbacks.

- [ ] **Step 3: Commit Gateway integration**

```bash
git add aap_gateway_api/authentication/reconcile.py aap_gateway_api/tests/authentication/test_authenticator_map_reconcile.py
git commit -m "feat: batch authenticator map permission sync"
```

### Task 5: End-to-end coverage, dependency wiring, and verification

**Files:**
- Modify: `atf/test-suite/tests/gateway/authentication/test_authenticator_mapping_permission_sync.py`
- Modify: DAB/Jewel PR dependency metadata.

- [ ] **Step 1: Add a multi-map ATF scenario**

Create two matching organization role maps for one user. Poll Controller until both grants appear, then change claims so one map no longer matches and poll until only that grant disappears. Reuse the current diagnostic output and condition-based polling; do not add fixed sleeps.

- [ ] **Step 2: Verify RED before the new endpoints are deployed**

Run:

```bash
pytest tests/gateway/authentication/test_authenticator_mapping_permission_sync.py -v
```

Expected: the multi-map immediate assertion fails against the old endpoint contract.

- [ ] **Step 3: Configure both PR revisions and verify GREEN**

Add the bulk DAB PR to Jewel's `Requires:` metadata, deploy/test with both revisions, then rerun the command from Step 2. Expected: grant and removal visibility converge before periodic component sync.

- [ ] **Step 4: Run final checks and push in dependency order**

```bash
cd /home/bhavenst/repos2/jewel/django-ansible-base
tox -m lint
ANSIBLE_BASE_TEST_DIRS='test_app/tests/rbac/remote/test_service_api.py test_app/tests/resource_registry/test_resources_api_rest_client.py' tox -e py312
ANSIBLE_BASE_TEST_DIRS='test_app/tests/rbac/remote/test_service_api.py' tox -e py312-sqlite

cd /home/bhavenst/repos2/jewel
ruff check aap_gateway_api/authentication/reconcile.py aap_gateway_api/tests/authentication/test_authenticator_map_reconcile.py
ruff format --check aap_gateway_api/authentication/reconcile.py aap_gateway_api/tests/authentication/test_authenticator_map_reconcile.py
GATEWAY_TEST_DIRS='' PYTEST_NUM_PROCESSES=1 tox -e py312 -- aap_gateway_api/tests/authentication/test_authenticator_map_reconcile.py aap_gateway_api/tests/utils/test_resources_client.py -v
```

Push DAB before Jewel, wait for both CI matrices, then reply to the performance review thread with the measured reduction from per-assignment to per-batch fan-out.
