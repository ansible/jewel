import logging
from typing import Any, Dict, List, Optional

from ansible_base.rbac.models import RoleDefinition
from ansible_base.rbac.remote import RemoteObject
from ansible_base.resource_registry.models import Resource

from aap_gateway_api.management.commands._migrate_service_data.cursor_store import CursorStore
from aap_gateway_api.models.service_type import DefaultServiceType

logger = logging.getLogger('aap.gateway.management.commands.migrate_service_data')


class RoleAssignmentsMixin:
    @staticmethod
    def _get_role_definitions_to_exclude(service_type: str) -> List[str]:
        # Since the goal is to honor controller's assignments platform roles, we do not want to consider
        # roles like 'Organization Admin' or 'Team Admin' from other services, just controller
        DEFAULT_EXCLUSION_SET = {'Platform Auditor', 'Organization Admin', 'Organization Member', 'Team Admin', 'Team Member'}
        ROLE_EXCLUSION_SETS = {
            # For controller, exclude nothing
            DefaultServiceType.CONTROLLER.value: {},
            # For hub, exclude platform roles but don't exclude 'Team Member'
            DefaultServiceType.HUB.value: DEFAULT_EXCLUSION_SET - {'Team Member'},
        }
        return sorted(ROLE_EXCLUSION_SETS.get(service_type, DEFAULT_EXCLUSION_SET))

    @staticmethod
    def _raise_fetch_error(response, assignment_type: str, page: int) -> None:
        """Log and raise RuntimeError for a failed assignment page fetch.

        Captures up to 500 characters of the response body so operators
        can diagnose upstream errors without searching service logs.
        """
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

    def _paginate_and_create(self, list_fn, assignment_type: str, roles_to_exclude: List[str], cursor: 'CursorStore') -> int:
        """Paginate one assignment endpoint using a PK cursor, creating assignments per page.

        Queries with ``order_by=id&id__gt=<snapshot_pk>`` so only
        assignments newer than the cursor are fetched.  The snapshot_pk
        is captured once and stays immutable for the entire run, preventing
        items from being skipped when the DB cursor advances between pages.

        On a reinstall where the cursor is already past the last PK,
        the first page returns zero results and the method returns
        immediately.

        No per-page retry -- the PK cursor provides crash recovery.
        If the command fails on an HTTP error, the installer re-runs
        it and the cursor resumes from the last completed page.

        Crash safety: the cursor is advanced in the database after each
        fully-processed page, so at most one page of work is lost.
        """
        page = 1
        created = 0

        # Build base filters once -- only 'page' changes between iterations.
        # snapshot_pk is immutable (set once in CursorStore.__init__).
        base_filters: Dict[str, Any] = {'order_by': 'id', **self.BIG_PAGE_FILTERS}
        if roles_to_exclude:
            base_filters['not__role_definition__name__in'] = ','.join(roles_to_exclude)
        if cursor.last_pk > 0:
            base_filters['id__gt'] = str(cursor.last_pk)

        while True:
            response = list_fn(filters={**base_filters, 'page': page})
            if response.status_code != 200:
                self._raise_fetch_error(response, assignment_type, page)

            data = response.json()
            results = data.get('results') or []
            if not results:
                break

            created += self._create_page_assignments(results, assignment_type)

            # Advance cursor in DB for crash recovery.  cursor.last_pk
            # is NOT mutated -- base_filters stays consistent.
            last_pk_on_page = results[-1].get('id')
            if last_pk_on_page is None:
                raise RuntimeError(
                    f"API returned {assignment_type} assignment without 'id' field -- "
                    f"cannot advance cursor. Check that the upstream service "
                    f"is running a compatible DAB version (requires PR 1032+)."
                )
            cursor.advance(last_pk_on_page)

            if not data.get('next'):
                break
            page += 1

        return created

    def _create_page_assignments(self, results: List[Dict[str, Any]], assignment_type: str) -> int:
        """Create assignments from one page of API results.

        Returns the number of assignments successfully created.
        give_permission is idempotent (uses get_or_create internally),
        so duplicates from cursor overlap are harmless.
        """
        created = 0
        for item in results:
            if self._create_assignment(item, assignment_type):
                created += 1
        return created

    def _create_assignment(self, assignment: Dict[str, Any], assignment_type: str) -> bool:
        """Resolve and create a single role assignment from a raw API response dict.

        Extracts actor, role, and content object identifiers from the API
        response, resolves them against the local database, and calls
        give_permission to create the assignment.

        Each resolution step has its own error handling with specific
        operator-facing messages that include actor, role, and object
        identifiers so failures can be debugged at scale.

        Returns True if the assignment was created, False if skipped.
        """
        # --- Extract actor and role from the API response ---
        actor_ansible_id = assignment.get(f'{assignment_type}_ansible_id')
        role_name = assignment.get('role_definition')
        if not actor_ansible_id or not role_name:
            return False

        # --- Resolve the content object identifier ---
        # org/team content types use object_ansible_id (looked up via
        # Resource), everything else uses the raw object_id (wrapped
        # in RemoteObject), and global assignments use None.
        content_type_str = assignment.get('content_type', '')
        model = content_type_str.split('.')[-1] if content_type_str else ''

        if model in ('organization', 'team'):
            object_ref = assignment.get('object_ansible_id')
        else:
            obj_id = assignment.get('object_id')
            object_ref = str(obj_id) if obj_id is not None else None

        # --- Look up the RoleDefinition ---
        try:
            role_definition = RoleDefinition.objects.get(name=role_name)
        except RoleDefinition.DoesNotExist:
            self._log(
                f"Warning: Unable to find role definition '{role_name}', skipping {assignment_type} assignment for actor {actor_ansible_id}",
                logging.WARNING,
            )
            return False

        # --- Resolve the actor via Resource ---
        try:
            actor_resource = Resource.objects.get(ansible_id=actor_ansible_id)
            actor = actor_resource.content_object
            # content_object is None when the underlying object was deleted
            # but the Resource row still exists (stale generic FK).
            if actor is None:
                self._log(
                    f"Warning: Resource {actor_ansible_id} exists but its {assignment_type} object was deleted, skipping assignment for role '{role_name}'",
                    logging.WARNING,
                )
                return False
        except Resource.DoesNotExist:
            self._log(
                f"Warning: Unable to find {assignment_type} with ansible_id {actor_ansible_id}, skipping assignment for role '{role_name}'",
                logging.WARNING,
            )
            return False

        # --- Create the assignment ---
        return self._give_assignment_permission(role_definition, actor, object_ref, assignment_type, actor_ansible_id, role_name)

    def _give_assignment_permission(
        self, role_definition: RoleDefinition, actor, object_ref: Optional[str], assignment_type: str, actor_ansible_id: str, role_name: str
    ) -> bool:
        """Resolve the content object and call give_permission.

        Handles three assignment patterns:
        - Global (object_ref is None): give_global_permission
        - Org/team (content_type.model in organization/team): resolve
          via Resource ansible_id
        - Service-specific: wrap in RemoteObject
        """
        try:
            if object_ref is None:
                role_definition.give_global_permission(actor)
                return True
            if role_definition.content_type and role_definition.content_type.model in ('organization', 'team'):
                return self._give_org_team_permission(role_definition, actor, object_ref, assignment_type, actor_ansible_id, role_name)
            remote_obj = RemoteObject(role_definition.content_type, object_ref)
            role_definition.give_permission(actor, remote_obj)
            return True
        except Resource.DoesNotExist:
            self._log(
                f"Warning: Unable to find content object with "
                f"ansible_id {object_ref}, "
                f"skipping {assignment_type} assignment for actor {actor_ansible_id} "
                f"with role '{role_name}'",
                logging.WARNING,
            )
            return False
        except Exception as e:
            self._log(
                f"Warning: Unable to give permission for {assignment_type} assignment "
                f"(actor={actor_ansible_id}, role='{role_name}', object={object_ref}), "
                f"skipping: {e}",
                logging.WARNING,
            )
            return False

    def _give_org_team_permission(
        self, role_definition: RoleDefinition, actor, object_ref: str, assignment_type: str, actor_ansible_id: str, role_name: str
    ) -> bool:
        """Resolve an org/team content object via Resource and call give_permission.

        Returns False if the Resource exists but its content_object was
        deleted (stale generic FK).
        """
        obj_resource = Resource.objects.get(ansible_id=object_ref)
        content_object = obj_resource.content_object
        if content_object is None:
            self._log(
                f"Warning: Resource {object_ref} exists but its "
                f"content object was deleted, "
                f"skipping {assignment_type} assignment for actor {actor_ansible_id} "
                f"with role '{role_name}'",
                logging.WARNING,
            )
            return False
        role_definition.give_permission(actor, content_object)
        return True

    def migrate_role_assignments(self, service_slug: str, service_type_name: str) -> None:
        """Migrate role assignments from a service using a PK-based cursor.

        For each assignment type (user, team), fetches only assignments with
        PKs higher than the stored cursor using ``id__gt=<last_pk>&order_by=id``.
        On a reinstall where the cursor is already past the last PK, the API
        returns zero results and migration completes immediately.

        The cursor is persisted per page, so a crash or kill loses at most
        one page of work.  HTTP errors raise RuntimeError to fail the
        service (non-zero exit for the installer to retry the whole command).

        After all pages are processed, a post-run drift check detects
        assignments created during the run.  If drift is found, RuntimeError
        is raised so the installer retries and the cursor picks up the
        new items.

        give_permission is idempotent (uses get_or_create), so replaying
        a partial page after a crash is safe.

        """
        self._log(f"Migrating role assignments from {service_slug} (type {service_type_name})", logging.INFO)
        roles_to_exclude = self._get_role_definitions_to_exclude(service_type_name)

        total_created = 0
        drift_detected = False
        for assignment_type in ('user', 'team'):
            list_fn = self.client.list_user_assignments if assignment_type == 'user' else self.client.list_team_assignments
            cursor = CursorStore(service_slug, assignment_type)
            created = self._paginate_and_create(list_fn, assignment_type, roles_to_exclude, cursor)
            total_created += created
            self._log(f"  {assignment_type}: {created} assignments created", logging.INFO)

            # Post-run drift check: detect assignments created on the
            # upstream service since the last page was fetched.  This is
            # one extra API call per type -- negligible overhead -- but it
            # restores the installer's ability to detect incomplete state.
            #
            # Note: this only captures items created between "last page
            # fetched" and "this check."  A tiny window remains between
            # this check and the migration flag being set, but that gap
            # is milliseconds and practically negligible.
            if self._check_for_drift(list_fn, assignment_type, service_slug):
                drift_detected = True

        self._log(f"Role assignment migration for {service_slug} completed ({total_created} total created)", logging.INFO)

        if drift_detected:
            raise RuntimeError(
                f"Role assignment migration for {service_slug} completed "
                f"({total_created} created) but concurrent modifications were "
                f"detected. Re-run to process remaining assignments."
            )

    def _check_for_drift(self, list_fn, assignment_type: str, service_slug: str) -> bool:
        """Check if new assignments appeared since the cursor was last advanced.

        Loads a fresh cursor from the DB (reflecting the last advance()
        call) and asks the API if any items exist beyond it.  Returns
        True if drift is detected, False otherwise.
        """
        db_cursor = CursorStore(service_slug, assignment_type)
        if db_cursor.last_pk <= 0:
            return False

        try:
            check_resp = list_fn(filters={'order_by': 'id', 'id__gt': str(db_cursor.last_pk), 'page_size': '1'})
            if check_resp.status_code == 200 and check_resp.json().get('count', 0) > 0:
                self._log(f"Warning: new {assignment_type} assignments appeared during migration of {service_slug} (concurrent modification)", logging.WARNING)
                return True
        except Exception:
            logger.warning(
                "Drift check failed for %s/%s, assuming no drift",
                service_slug,
                assignment_type,
                exc_info=True,
            )
        return False
