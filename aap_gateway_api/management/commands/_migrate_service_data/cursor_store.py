import logging
import traceback

from django.db import connection

logger = logging.getLogger('aap.gateway.management.commands.migrate_service_data')


class CursorStore:
    """Raw-SQL cursor for PK-based role assignment pagination.

    Stores (service_slug, assignment_type, last_pk) tuples in a
    self-managed database table, avoiding Django migrations entirely.
    This makes the cursor self-bootstrapping on any branch and
    trivial to backport across versions.

    Key invariant: self.last_pk is set once in __init__ and NEVER
    mutated.  advance() only persists progress to the database.
    This ensures the HTTP id__gt filter stays immutable across all
    pages of a single run, preventing items from being skipped when
    the cursor advances in the database between pages.

    If any database operation fails, the store degrades gracefully
    to last_pk=0, causing the command to reprocess all assignments.
    Since give_permission is idempotent, this is safe -- the worst
    case is slower, not incorrect.
    """

    _TABLE = "migrate_service_data_role_cursor"

    # Pre-built SQL — table name is baked in at class definition so
    # execute() receives plain strings, not f-strings.
    _SQL_CREATE = (
        f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
        "  service_slug VARCHAR(255) NOT NULL,"
        "  assignment_type VARCHAR(16) NOT NULL,"
        "  last_pk BIGINT NOT NULL DEFAULT 0,"
        "  PRIMARY KEY (service_slug, assignment_type)"
        ")"
    )
    _SQL_LOAD = f"SELECT last_pk FROM {_TABLE} WHERE service_slug = %s AND assignment_type = %s"
    _SQL_UPSERT = (
        f"INSERT INTO {_TABLE}"
        " (service_slug, assignment_type, last_pk)"
        " VALUES (%s, %s, %s)"
        " ON CONFLICT (service_slug, assignment_type)"
        " DO UPDATE SET last_pk = EXCLUDED.last_pk"
    )

    def __init__(self, service_slug, assignment_type, log_fn=None):
        """Load the cursor from DB, setting self.last_pk once (immutably)."""
        self.service_slug = service_slug
        self.assignment_type = assignment_type
        self._log_fn = log_fn
        # Set once at init; not updated by advance(). Do not read mid-run
        # as a DB failure during advance() leaves this stale at 0.
        self.last_pk = self._load()

    def _ensure_table(self):
        """Create the cursor table if it does not already exist."""
        with connection.cursor() as cur:
            cur.execute(self._SQL_CREATE)

    def _load(self) -> int:
        """Read current cursor value from DB, returning 0 on any failure."""
        try:
            self._ensure_table()
            with connection.cursor() as cur:
                cur.execute(self._SQL_LOAD, [self.service_slug, self.assignment_type])
                row = cur.fetchone()
                return row[0] if row else 0
        except Exception:
            msg = f"Failed to load cursor for {self.service_slug}/{self.assignment_type}, will reprocess all assignments"
            if self._log_fn:
                self._log_fn(f"{msg}\n{traceback.format_exc()}", logging.WARNING)
            else:
                logger.warning(msg, exc_info=True)
            return 0

    def advance(self, pk):
        """Persist progress to DB without mutating self.last_pk.

        The in-memory last_pk stays at its initial value so the HTTP
        id__gt filter remains consistent across all pages of a run.
        If the upsert fails, a warning is logged but the run continues --
        the next invocation will reprocess from the old position, which
        is safe because bulk_create with ignore_conflicts is idempotent.
        """
        try:
            with connection.cursor() as cur:
                cur.execute(self._SQL_UPSERT, [self.service_slug, self.assignment_type, pk])
        except Exception:
            msg = f"Failed to advance cursor for {self.service_slug}/{self.assignment_type} to {pk}; next run will reprocess from the old position"
            if self._log_fn:
                self._log_fn(f"{msg}\n{traceback.format_exc()}", logging.WARNING)
            else:
                logger.warning(msg, exc_info=True)
