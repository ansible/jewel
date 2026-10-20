# Role Assignment Batch Sync Design

## Goal

Synchronize role-assignment changes from Gateway to connected AAP services immediately without issuing one service-index request for every changed assignment. The transport must support grants and removals and be reusable by future bulk role-assignment producers.

## Current state

Authenticator-map reconciliation in DAB calculates the desired role assignments and applies each change locally. Gateway currently observes each returned grant and invokes `AllServicesClient.sync_assignment()`. The client fans that one assignment out to every registered downstream service. A user matching hundreds of role maps therefore creates hundreds of requests per service. Removals currently receive no immediate downstream synchronization.

DAB already has bulk database permission primitives, but service-index role-assignment endpoints and clients only support individual `assign` and `unassign` requests. The individual endpoints must remain compatible for direct role APIs and existing consumers.

## Design

### Typed service-index bulk actions

Keep user and team assignments on their existing typed routes. Add four collection actions:

- `POST role-user-assignments/bulk-assign/`
- `POST role-user-assignments/bulk-unassign/`
- `POST role-team-assignments/bulk-assign/`
- `POST role-team-assignments/bulk-unassign/`

The `bulk-*` convention matches the existing `resources/bulk-update/` service-index endpoint. Do not add a nested `assign/bulk/` action or a combined user/team endpoint.

Each request has common operation metadata and an array of the existing assignment item shape:

```json
{
  "from_service": "gateway-service-uuid",
  "created_by_ansible_id": "optional-common-creator-uuid",
  "assignments": [
    {
      "role_definition": "Organization Execute",
      "user_ansible_id": "user-uuid",
      "object_ansible_id": "organization-uuid"
    }
  ]
}
```

`from_service` is required request metadata and is not repeated per item. `created_by_ansible_id` is optional request metadata. A generic sender groups assignments by creator before constructing requests when necessary. Gateway authenticator-map batches omit this field when the creator is Gateway's `_system` user because that implementation-local user has no Resource in downstream components; receivers retain their existing local-system-user default.

The assignment object payload deliberately reuses the single-item serializer fields. This preserves object-addressing behavior: registered shared resources use `object_ansible_id`; unregistered or service-owned resources use `object_id`; global assignments use the existing null object representation.

### Receiver behavior

Bulk actions are synchronous component API requests even though Gateway dispatches them asynchronously. The receiver:

1. validates the request wrapper and every assignment item before mutating data;
2. resolves actors, role definitions, and content objects in bulk;
3. applies the operation inside one database transaction using DAB bulk permission primitives;
4. performs the batch equivalent of any service-specific secondary-sync hook; and
5. returns one aggregate response.

The response is `200 OK` for a successfully processed batch. Grants report `created` and `existing` counts; removals report `deleted` and `missing` counts. Invalid structure or unresolved data returns `400 Bad Request`; authorization failure returns `403 Forbidden`. A validation or authorization failure rolls back the entire batch—there is no partial mutation.

Do not return `202 Accepted` or introduce a background job/status endpoint. `AllServicesClient(wait_for_response=False)` already makes the Gateway login path non-blocking while its worker receives the actual component response, logs it, and invokes the callback.

### Generic DAB client

Extend DAB's `ResourceAPIClient` with generic typed batch methods for grants and removals. They serialize assignment objects or removal triples, lift common `from_service` and creator data into the wrapper, group by user/team and creator as needed, and post to the corresponding bulk action.

`AllServicesClient` inherits these methods. Its existing fan-out executes one request per target service per typed operation batch. The existing ten-worker executor continues to constrain concurrent requests, but it no longer accumulates one queued task per assignment.

Existing `sync_assignment()` and `sync_unassignment()` methods and their single-item endpoints remain unchanged.

### Gateway authenticator-map integration

Gateway's configured DAB reconciler collects changes for the duration of one `apply_permissions()` call:

- `_give_permission()` retains every newly created assignment returned by DAB.
- `_remove_permission()` records the role definition, user, and content object before removal.
- Once local reconciliation finishes, the reconciler sends collected user grants and removals through the generic batch client.

The initial caller is authenticator-map reconciliation, but neither the DAB transport nor the client is authenticator-specific. A later producer can call the generic batch client without altering the service-index protocol.

### Failure and compatibility behavior

Gateway does not delay login waiting for component batch responses. Callback logging records successful, timeout, missing-response, and non-2xx outcomes, including the response body for a failed request. The established periodic component-to-Gateway synchronization remains the recovery path for an unavailable component or a rejected bulk request.

During rolling deployment, a component that has not adopted the new DAB endpoint returns a route-not-found response. Gateway logs it; its periodic synchronization still converges state. The feature requires the DAB bulk-endpoint change to merge and release before the Jewel integration is enabled in a component build.

## Test strategy

### DAB

- Wrapper serializer validation: shared request metadata, missing assignment list, empty list, and item validation errors.
- User and team grant batches: bulk creation plus idempotent repeat reporting.
- User and team removal batches: deletion plus idempotent repeat reporting.
- Atomicity: one malformed or unauthorized item changes no assignments.
- Client serialization: common source/creator metadata is lifted once, `_system` creator is omitted, and user/team/creator grouping selects the expected route.
- Existing single-item assign and unassign tests remain green without payload changes.

### Jewel

- Reconciler with multiple grants performs one user bulk-grant call instead of one call per assignment.
- Reconciler with multiple removals performs one user bulk-removal call.
- Mixed grant/removal reconciliation sends one request for each operation type.
- Empty change lists issue no service requests.
- Existing callback tests cover successful, missing, and non-2xx responses for the new batch requests.

### Integration

Extend the authenticator-map ATF scenario with multiple mapped roles and verify Controller sees the expected grants and removals before its periodic sync task. The assertion must observe immediate convergence without depending on a fixed sleep.

## Non-goals

- Do not automatically batch every existing direct role API call or alter its synchronous error behavior.
- Do not replace periodic component synchronization; it remains the recovery and eventual-consistency mechanism.
- Do not add a general asynchronous job framework for role synchronization.
- Do not create a cross-type user/team endpoint.

## Compatibility and rollout order

1. Merge and release the DAB bulk service-index API and client support.
2. Update Jewel to use the new generic batch methods for authenticator-map reconciliation.
3. Build/deploy components with the DAB revision before expecting immediate bulk propagation from Gateway.

Jewel retains its existing `Requires: ansible/django-ansible-base#1182` relationship for the assignment-return contract. The bulk DAB change will add the corresponding dependency before implementation starts.
