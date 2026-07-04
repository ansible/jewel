"""Tests for CursorStore — raw SQL cursor for PK-based role assignment pagination.

The cursor's key invariant: self.last_pk is set once in __init__ and
never mutated.  advance() only persists to the database.  This ensures
the HTTP id__gt filter stays immutable across all pages of a single run.
"""

from unittest.mock import patch

import pytest

from aap_gateway_api.management.commands._migrate_service_data.cursor_store import CursorStore


@pytest.mark.django_db
class TestCursorStore:
    def test_fresh_cursor_has_zero_last_pk(self):
        """A new cursor with no prior data starts at 0."""
        cursor = CursorStore("controller", "user")
        assert cursor.last_pk == 0

    def test_advance_persists_without_mutating_last_pk(self):
        """advance() writes to DB but does NOT change self.last_pk.

        This is the key invariant that prevents the pagination bug where
        advancing the cursor between pages causes items to be skipped.
        """
        cursor = CursorStore("controller", "user")
        assert cursor.last_pk == 0

        cursor.advance(42)

        # In-memory value is still 0 -- immutable after __init__
        assert cursor.last_pk == 0

        # But a new cursor for the same key reads 42 from DB
        cursor2 = CursorStore("controller", "user")
        assert cursor2.last_pk == 42

    def test_new_cursor_reads_advanced_value(self):
        """After advance(), a new CursorStore for the same key reads the persisted value."""
        cursor = CursorStore("hub", "team")
        cursor.advance(100)

        reloaded = CursorStore("hub", "team")
        assert reloaded.last_pk == 100

    def test_unique_per_service_and_type(self):
        """Each (service_slug, assignment_type) pair gets its own independent cursor."""
        c1 = CursorStore("controller", "user")
        c2 = CursorStore("controller", "team")
        c3 = CursorStore("hub", "user")

        c1.advance(10)
        c2.advance(20)
        c3.advance(30)

        assert CursorStore("controller", "user").last_pk == 10
        assert CursorStore("controller", "team").last_pk == 20
        assert CursorStore("hub", "user").last_pk == 30

    def test_graceful_degradation_on_load_error(self):
        """If the database is unreachable during load, last_pk defaults to 0.

        This ensures the command can still run (reprocessing all assignments)
        rather than failing outright on a cursor table issue.
        """
        cursor_mod = "aap_gateway_api.management.commands._migrate_service_data.cursor_store.connection"
        with patch(cursor_mod) as mock_conn:
            mock_conn.cursor.side_effect = RuntimeError("DB unavailable")
            cursor = CursorStore("controller", "user")

        assert cursor.last_pk == 0

    def test_graceful_degradation_on_advance_error(self):
        """If the database fails during advance(), a warning is logged but
        no exception is raised.

        The next invocation will reprocess from the old cursor position,
        which is safe because give_permission is idempotent.
        """
        cursor = CursorStore("controller-adv-err", "user")

        cursor_mod = "aap_gateway_api.management.commands._migrate_service_data.cursor_store.connection"
        with patch(cursor_mod) as mock_conn:
            mock_conn.cursor.side_effect = RuntimeError("DB unavailable")
            # Should not raise -- degrades gracefully
            cursor.advance(42)

        # The advance failed, so a new cursor should still read 0
        new_cursor = CursorStore("controller-adv-err", "user")
        assert new_cursor.last_pk == 0
