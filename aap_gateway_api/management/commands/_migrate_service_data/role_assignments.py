import logging
import traceback
from typing import Any, Dict, List, Tuple

from ansible_base.rbac.caching import compute_object_role_permissions, compute_team_member_roles
from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleTeamAssignment, RoleUserAssignment
from ansible_base.resource_registry.models import Resource
from django.db.models import Q

from aap_gateway_api.management.commands._migrate_service_data.cursor_store import CursorStore
from aap_gateway_api.models.service_type import DefaultServiceType

logger = logging.getLogger('aap.gateway.management.commands.migrate_service_data')


class RoleAssignmentsMixin:
    @staticmethod
    def _get_role_definitions_to_exclude(service_type: str) -> List[str]:
        DEFAULT_EXCLUSION_SET = {'Platform Auditor', 'Organization Admin', 'Organization Member', 'Team Admin', 'Team Member'}
        ROLE_EXCLUSION_SETS = {
            DefaultServiceType.CONTROLLER.value: {},
            DefaultServiceType.HUB.value: DEFAULT_EXCLUSION_SET - {'Team Member'},
        }
        return sorted(ROLE_EXCLUSION_SETS.get(service_type, DEFAULT_EXCLUSION_SET))

    @staticmethod
    def _raise_fetch_error(response, assignment_type: str, page: int) -> None:
        """Log and raise RuntimeError for a failed assignment page fetch."""
        body_preview = ""
        try:
            body_preview = response.text[:500]
        except Exception:
            pass
        logger.warning(
            "HTTP %d fetching %s assignments page %d",
            response.status_code,
            assignment_type,
            page,
        )
        raise RuntimeError(f"Failed to fetch {assignment_type} assignments page {page}: HTTP {response.status_code}\n{body_preview}")

    def _paginate_and_create(self, list_fn, assignment_type: str, roles_to_exclude: List[str], cursor: 'CursorStore') -> Tuple[int, set]:
        """Paginate one assignment endpoint using id__gt sliding window,
        bulk-creating assignments per page.

        Always requests with ``id__gt=<last_pk>`` so the window slides
        forward after each batch.  This is stable against mid-run
        deletions and doubles as crash recovery since the cursor is
        persisted to the database after each page.

        Returns (created_count, object_roles_set) for deferred cache rebuild.
        """
        created = 0
        all_object_roles: set = set()
        total = None

        base_filters: Dict[str, Any] = {'order_by': 'id', 'id__gt': str(cursor.last_pk), **self.BIG_PAGE_FILTERS}
        if roles_to_exclude:
            base_filters['not__role_definition__name__in'] = ','.join(roles_to_exclude)

        progress_label = f"{assignment_type} role assignments"

        while True:
            response = list_fn(filters=base_filters)
            if response.status_code != 200:
                self._raise_fetch_error(response, assignment_type, 0)

            data = response.json()
            results = data.get('results') or []
            if not results:
                break

            if total is None:
                total = data.get('count', 0)

            page_created, page_object_roles = self._bulk_resolve_and_create_page(results, assignment_type)
            created += page_created
            all_object_roles.update(page_object_roles)

            if total:
                self._log_progress(progress_label, created, total)

            last_pk_on_page = results[-1].get('id')
            if last_pk_on_page is not None:
                cursor.advance(last_pk_on_page)
                base_filters['id__gt'] = str(last_pk_on_page)
            else:
                raise RuntimeError(f"API returned {assignment_type} assignment without 'id' field — cannot advance cursor")

        return created, all_object_roles

    @staticmethod
    def _collect_unique_ids(results: List[Dict[str, Any]], actor_field: str) -> Tuple[set, set, set]:
        """Extract unique role names, actor IDs, and object IDs from a results page."""
        role_names: set = set()
        actor_ansible_ids: set = set()
        object_ansible_ids: set = set()

        for item in results:
            rn = item.get('role_definition')
            if rn:
                role_names.add(rn)
            aid = item.get(actor_field)
            if aid:
                actor_ansible_ids.add(str(aid))
            oid = item.get('object_ansible_id')
            if oid:
                object_ansible_ids.add(str(oid))

        return role_names, actor_ansible_ids, object_ansible_ids

    def _resolve_single_assignment(
        self,
        item: Dict[str, Any],
        actor_field: str,
        assignment_type: str,
        role_map: Dict[str, Any],
        actor_resource_map: Dict[str, Any],
        object_resource_map: Dict[str, Any],
    ) -> 'Tuple[str, Tuple] | None':
        """Resolve one API assignment item into a classified tuple.

        Returns ``('global', tuple)`` or ``('object', tuple)`` on success,
        or ``None`` when the item must be skipped.
        """
        actor_ansible_id = item.get(actor_field)
        role_name = item.get('role_definition')
        if not actor_ansible_id or not role_name:
            return None

        rd = role_map.get(role_name)
        if rd is None:
            self._log(f"Warning: Unable to find role definition '{role_name}', skipping assignment", logging.WARNING)
            return None

        actor_resource = actor_resource_map.get(str(actor_ansible_id))
        if actor_resource is None:
            self._log(
                f"Warning: Unable to find {assignment_type} with ansible_id {actor_ansible_id}, skipping assignment",
                logging.WARNING,
            )
            return None
        actor_pk = actor_resource.object_id

        if assignment_type == 'user' and getattr(actor_resource.content_object, 'is_superuser', False):
            self._log(
                f"Skipping assignment for superuser '{actor_resource.content_object.username}': "
                f"superusers bypass RBAC, role assignments are unnecessary",
                logging.INFO,
            )
            return None

        object_ansible_id = item.get('object_ansible_id')
        object_id = item.get('object_id')

        if object_ansible_id:
            obj_resource = object_resource_map.get(str(object_ansible_id))
            if obj_resource is None:
                self._log(
                    f"Warning: Unable to find object with ansible_id {object_ansible_id}, skipping assignment",
                    logging.WARNING,
                )
                return None
            return ('object', (actor_pk, rd, rd.content_type_id, str(obj_resource.object_id), actor_ansible_id))
        elif object_id is not None:
            return ('object', (actor_pk, rd, rd.content_type_id, str(object_id), actor_ansible_id))
        else:
            return ('global', (actor_pk, rd, None, None, actor_ansible_id))

    def _bulk_resolve_and_create_page(self, results: List[Dict[str, Any]], assignment_type: str) -> Tuple[int, set]:
        """Resolve all assignments on a page using bulk queries and bulk-create them.

        Returns (created_count, object_roles_set) for deferred cache rebuild.
        """
        actor_field = f'{assignment_type}_ansible_id'

        role_names, actor_ansible_ids, object_ansible_ids = self._collect_unique_ids(results, actor_field)

        role_map = {rd.name: rd for rd in RoleDefinition.objects.filter(name__in=role_names)}
        actor_resource_map = {str(r.ansible_id): r for r in Resource.objects.filter(ansible_id__in=actor_ansible_ids)} if actor_ansible_ids else {}
        object_resource_map = {str(r.ansible_id): r for r in Resource.objects.filter(ansible_id__in=object_ansible_ids)} if object_ansible_ids else {}

        global_assignments: List[Tuple] = []
        object_assignments: List[Tuple] = []

        for item in results:
            resolved = self._resolve_single_assignment(item, actor_field, assignment_type, role_map, actor_resource_map, object_resource_map)
            if resolved is None:
                continue
            kind, assignment_tuple = resolved
            if kind == 'global':
                global_assignments.append(assignment_tuple)
            else:
                object_assignments.append(assignment_tuple)

        created = 0
        object_roles_used: set = set()

        if global_assignments:
            created += self._bulk_create_global_assignments(global_assignments, assignment_type)

        if object_assignments:
            count, obj_roles = self._bulk_create_object_assignments(object_assignments, assignment_type)
            created += count
            object_roles_used.update(obj_roles)

        return created, object_roles_used

    def _bulk_create_global_assignments(self, assignments: List[Tuple], assignment_type: str) -> int:
        """Bulk-create global (system-wide) role assignments.

        Because PostgreSQL treats NULL != NULL, the unique constraint on
        (user, object_role) does not prevent duplicates when object_role
        is None.  We therefore query for existing global assignments and
        filter them out before calling bulk_create.
        """
        AssignmentModel = RoleUserAssignment if assignment_type == 'user' else RoleTeamAssignment  # NOSONAR
        actor_field = 'user_id' if assignment_type == 'user' else 'team_id'

        # Build the set of (actor_pk, role_def_id) we want to create
        # Cast actor_pk to int for comparison since values_list returns int FKs
        desired = {(actor_pk, rd.id) for actor_pk, rd, _, _, _ in assignments}

        # Query existing global assignments (object_role=None) for these combos
        existing = set(
            AssignmentModel.objects.filter(
                object_role__isnull=True,
                **{f'{actor_field}__in': {a[0] for a in desired}},
                role_definition_id__in={a[1] for a in desired},
            ).values_list(actor_field, 'role_definition_id')
        )

        # Only create ones that don't exist
        # Cast actor_pk to match the int type returned by values_list
        new_assignments = [(a, rd, ct, oid, aid) for a, rd, ct, oid, aid in assignments if (int(a), rd.id) not in existing]

        assignment_objs = [
            AssignmentModel(
                **{actor_field: actor_pk},
                object_role=None,
                role_definition_id=rd.id,
                content_type_id=None,
                object_id=None,
            )
            for actor_pk, rd, _, _, _ in new_assignments
        ]

        result = AssignmentModel.objects.bulk_create(assignment_objs, ignore_conflicts=True)
        return len(result)

    def _bulk_create_object_assignments(self, assignments: List[Tuple], assignment_type: str) -> Tuple[int, set]:
        """Bulk-create ObjectRoles and object-scoped role assignments."""
        unique_or_keys: set = set()
        for _, rd, content_type_id, object_id, _ in assignments:
            unique_or_keys.add((rd.id, content_type_id, object_id))

        or_objs_to_create = [ObjectRole(role_definition_id=rd_id, content_type_id=ct_id, object_id=obj_id) for rd_id, ct_id, obj_id in unique_or_keys]
        ObjectRole.objects.bulk_create(or_objs_to_create, ignore_conflicts=True)

        or_query = Q()
        for rd_id, ct_id, obj_id in unique_or_keys:
            or_query |= Q(role_definition_id=rd_id, content_type_id=ct_id, object_id=obj_id)

        or_map: Dict[Tuple, ObjectRole] = {}
        for obj_role in ObjectRole.objects.filter(or_query):
            key = (obj_role.role_definition_id, obj_role.content_type_id, obj_role.object_id)
            or_map[key] = obj_role

        AssignmentModel = RoleUserAssignment if assignment_type == 'user' else RoleTeamAssignment  # NOSONAR
        actor_field = 'user_id' if assignment_type == 'user' else 'team_id'

        assignment_objs = []
        for actor_pk, rd, content_type_id, object_id, actor_ansible_id in assignments:
            or_key = (rd.id, content_type_id, object_id)
            object_role = or_map.get(or_key)
            if object_role is None:
                self._log(
                    f"Warning: ObjectRole not found for (rd={rd.name}, ct={content_type_id}, "
                    f"object={object_id}), skipping assignment for actor {actor_ansible_id}",
                    logging.WARNING,
                )
                continue

            assignment_objs.append(
                AssignmentModel(
                    **{actor_field: actor_pk},
                    object_role=object_role,
                    role_definition_id=object_role.role_definition_id,
                    content_type_id=object_role.content_type_id,
                    object_id=object_role.object_id,
                )
            )

        result = AssignmentModel.objects.bulk_create(assignment_objs, ignore_conflicts=True)
        return len(result), set(or_map.values())

    def migrate_role_assignments(self, service_slug: str, service_type_name: str) -> None:
        """Migrate role assignments from a service using bulk queries.

        The RBAC cache is rebuilt once at the end in a finally block,
        not per-assignment.

        Drift detection (checking for new assignments created during migration)
        was removed because the id__gt sliding window naturally handles this:
        new assignments get higher PKs and appear on subsequent pages. The only
        undetected window is assignments created during the final page's
        processing, which is sub-second.
        """
        self._log(f"Migrating role assignments from {service_slug} (type {service_type_name})", logging.INFO)
        roles_to_exclude = self._get_role_definitions_to_exclude(service_type_name)

        total_created = 0
        all_object_roles: set = set()

        try:
            for assignment_type in ('user', 'team'):
                list_fn = self.client.list_user_assignments if assignment_type == 'user' else self.client.list_team_assignments
                cursor = CursorStore(service_slug, assignment_type, log_fn=self._log)
                created, object_roles = self._paginate_and_create(list_fn, assignment_type, roles_to_exclude, cursor)
                total_created += created
                all_object_roles.update(object_roles)
                self._log(f"  {assignment_type}: {created} assignments created", logging.INFO)
        finally:
            if total_created:
                try:
                    self._log(
                        f"Rebuilding RBAC cache ({total_created} assignments created, {len(all_object_roles)} object roles)",
                        logging.INFO,
                    )
                    compute_team_member_roles()
                    if all_object_roles:
                        compute_object_role_permissions(object_roles=all_object_roles)
                except Exception:  # noqa: BLE001 — intentionally broad to avoid masking the original migration exception
                    self._log(f"Warning: RBAC cache rebuild failed, it will be rebuilt on next request\n{traceback.format_exc()}", logging.WARNING)

        self._log(f"Role assignment migration for {service_slug} completed ({total_created} total created)", logging.INFO)
