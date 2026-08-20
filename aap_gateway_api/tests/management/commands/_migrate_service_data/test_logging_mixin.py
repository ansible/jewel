"""Tests for LoggingMixin: _log_progress, _configure_logging, _log, _copy_console_handler_config."""

import logging
from io import StringIO

import pytest

from aap_gateway_api.management.commands.migrate_service_data import Command as MigrateCommand

MIGRATE_LOGGER_NAME = "aap.gateway.management.commands.migrate_service_data"


@pytest.fixture(autouse=True)
def _restore_migrate_logger_state():
    migrate_logger = logging.getLogger(MIGRATE_LOGGER_NAME)
    original_handlers = migrate_logger.handlers[:]
    original_level = migrate_logger.level
    original_propagate = migrate_logger.propagate
    try:
        yield
    finally:
        for handler in migrate_logger.handlers[:]:
            handler.close()
        migrate_logger.handlers = original_handlers
        migrate_logger.setLevel(original_level)
        migrate_logger.propagate = original_propagate


# =============================================================================
# _log_progress tests
# =============================================================================


def test_log_progress_emits_at_thresholds(caplog):
    """Test that progress is logged at 5% threshold crossings."""
    cmd = MigrateCommand()
    cmd._progress_thresholds = {}

    with caplog.at_level("INFO", logger=MIGRATE_LOGGER_NAME):
        for i in range(1, 101):
            cmd._log_progress("test", i, 100)

    progress_msgs = [msg for msg in caplog.messages if "Migration progress [test]" in msg]
    assert len(progress_msgs) == 21  # 0% + 5% through 100%
    assert "(0%)" in progress_msgs[0]
    assert "(100%)" in progress_msgs[-1]


def test_log_progress_zero_items(caplog):
    """Test that zero items logs a single message."""
    cmd = MigrateCommand()
    cmd._progress_thresholds = {}

    with caplog.at_level("INFO", logger=MIGRATE_LOGGER_NAME):
        cmd._log_progress("empty", 0, 0)

    progress_msgs = [msg for msg in caplog.messages if "Migration progress [empty]" in msg]
    assert len(progress_msgs) == 1
    assert "0 items to process" in progress_msgs[0]


def test_log_progress_small_count_skips_intermediate(caplog):
    """Test that small counts skip intermediate thresholds."""
    cmd = MigrateCommand()
    cmd._progress_thresholds = {}

    with caplog.at_level("INFO", logger=MIGRATE_LOGGER_NAME):
        for i in range(1, 11):
            cmd._log_progress("small", i, 10)

    progress_msgs = [msg for msg in caplog.messages if "Migration progress [small]" in msg]
    assert not any("(5%)" in msg for msg in progress_msgs)
    assert any("(10%)" in msg for msg in progress_msgs)


def test_log_progress_bookends_always_logged(caplog):
    """Test that first and last items always generate log output."""
    cmd = MigrateCommand()
    cmd._progress_thresholds = {}

    with caplog.at_level("INFO", logger=MIGRATE_LOGGER_NAME):
        cmd._log_progress("bookend", 1, 7)
        cmd._log_progress("bookend", 7, 7)

    progress_msgs = [msg for msg in caplog.messages if "Migration progress [bookend]" in msg]
    assert len(progress_msgs) >= 2
    assert "1/7" in progress_msgs[0]
    assert "7/7" in progress_msgs[-1]
    assert "(100%)" in progress_msgs[-1]


def test_log_progress_no_duplicate_100(caplog):
    """Test that 100% is not logged twice when last item lands exactly on a threshold."""
    cmd = MigrateCommand()
    cmd._progress_thresholds = {}

    with caplog.at_level("INFO", logger=MIGRATE_LOGGER_NAME):
        for i in range(1, 21):
            cmd._log_progress("exact", i, 20)

    progress_msgs = [msg for msg in caplog.messages if "(100%)" in msg and "exact" in msg]
    assert len(progress_msgs) == 1


# =============================================================================
# _configure_logging tests
# =============================================================================


def test_configure_logging_with_log_file(tmp_path):
    """When --log-file is provided, logger gets a StreamHandler at INFO."""
    cmd = MigrateCommand()
    log_file = tmp_path / "test.log"

    cmd._configure_logging(str(log_file))

    migrate_logger = logging.getLogger(MIGRATE_LOGGER_NAME)
    assert len(migrate_logger.handlers) == 1
    assert isinstance(migrate_logger.handlers[0], logging.StreamHandler)
    assert migrate_logger.level <= logging.INFO
    assert not migrate_logger.propagate

    cmd._log_file_handle.close()


def test_configure_logging_without_log_file():
    """When --log-file is omitted, logger gets a NullHandler."""
    cmd = MigrateCommand()

    cmd._configure_logging(None)

    migrate_logger = logging.getLogger(MIGRATE_LOGGER_NAME)
    assert len(migrate_logger.handlers) == 1
    assert isinstance(migrate_logger.handlers[0], logging.NullHandler)
    assert not migrate_logger.propagate


def test_configure_logging_closes_previous_file_handle(tmp_path):
    """Calling _configure_logging twice closes the previous file handle."""
    cmd = MigrateCommand()
    first_log = tmp_path / "first.log"
    second_log = tmp_path / "second.log"

    cmd._configure_logging(str(first_log))
    first_handle = cmd._log_file_handle
    assert not first_handle.closed

    cmd._configure_logging(str(second_log))
    assert first_handle.closed
    assert not cmd._log_file_handle.closed

    cmd._log_file_handle.close()


def test_configure_logging_respects_lower_level(tmp_path):
    """If the logger is already at DEBUG, _configure_logging should not raise it to INFO."""
    migrate_logger = logging.getLogger(MIGRATE_LOGGER_NAME)
    migrate_logger.setLevel(logging.DEBUG)

    cmd = MigrateCommand()
    cmd._configure_logging(str(tmp_path / "test.log"))

    assert migrate_logger.level == logging.DEBUG

    cmd._log_file_handle.close()


def test_configure_logging_inherits_formatter(tmp_path):
    """When the aap logger has a console handler with a formatter, it should be reused."""
    aap_logger = logging.getLogger("aap")
    original_handlers = aap_logger.handlers[:]
    test_formatter = logging.Formatter("TEST %(message)s")
    test_handler = logging.StreamHandler()
    test_handler.setFormatter(test_formatter)
    aap_logger.handlers = [test_handler]

    try:
        cmd = MigrateCommand()
        cmd._configure_logging(str(tmp_path / "test.log"))

        migrate_logger = logging.getLogger(MIGRATE_LOGGER_NAME)
        assert migrate_logger.handlers[0].formatter is test_formatter
        cmd._log_file_handle.close()
    finally:
        aap_logger.handlers = original_handlers


# =============================================================================
# _log tests
# =============================================================================


def test_log_info_writes_to_stdout(caplog):
    """_log at INFO writes to stdout and the logger."""
    cmd = MigrateCommand()
    cmd.stdout = StringIO()

    with caplog.at_level("INFO", logger=MIGRATE_LOGGER_NAME):
        cmd._log("test info message", logging.INFO)

    assert "test info message" in cmd.stdout.getvalue()
    assert "test info message" in caplog.messages


def test_log_warning_writes_to_stderr(caplog):
    """_log at WARNING writes to stderr and the logger."""
    cmd = MigrateCommand()
    cmd.stderr = StringIO()

    with caplog.at_level("WARNING", logger=MIGRATE_LOGGER_NAME):
        cmd._log("test warning message", logging.WARNING)

    assert "test warning message" in cmd.stderr.getvalue()
    assert "test warning message" in caplog.messages


def test_log_writes_to_log_file(tmp_path):
    """_log writes structured output to --log-file."""
    cmd = MigrateCommand()
    log_file = tmp_path / "test.log"

    cmd._configure_logging(str(log_file))
    cmd._log("file output test", logging.INFO)
    cmd._log_file_handle.flush()

    content = log_file.read_text()
    assert "file output test" in content
    assert "INFO" in content

    cmd._log_file_handle.close()


def test_log_file_not_written_without_flag(tmp_path, caplog):
    """Without --log-file, logger messages go to NullHandler only."""
    cmd = MigrateCommand()
    cmd.stdout = StringIO()
    cmd._configure_logging(None)

    with caplog.at_level("INFO", logger=MIGRATE_LOGGER_NAME):
        cmd._log("null handler test", logging.INFO)

    assert "null handler test" in cmd.stdout.getvalue()
    assert "null handler test" not in caplog.messages


def test_log_splits_newlines_for_logger(caplog):
    """_log splits messages on newlines so each line gets a formatter prefix."""
    cmd = MigrateCommand()
    cmd.stdout = StringIO()

    with caplog.at_level("INFO", logger=MIGRATE_LOGGER_NAME):
        cmd._log("\n=== Section Header ===", logging.INFO)

    assert "\n=== Section Header ===" in cmd.stdout.getvalue()
    assert "=== Section Header ===" in caplog.messages
    assert "" not in caplog.messages


def test_log_splits_multiline_message(caplog):
    """Multi-line messages produce one log record per non-empty line."""
    cmd = MigrateCommand()
    cmd.stderr = StringIO()

    with caplog.at_level("WARNING", logger=MIGRATE_LOGGER_NAME):
        cmd._log("line one\nline two\n\nline four", logging.WARNING)

    assert "line one" in caplog.messages
    assert "line two" in caplog.messages
    assert "line four" in caplog.messages
    assert len([m for m in caplog.messages if m in ("line one", "line two", "line four")]) == 3


# =============================================================================
# _copy_console_handler_config tests
# =============================================================================


def test_copy_console_handler_config_no_aap_handlers(tmp_path):
    """When the aap logger has no handlers, _copy_console_handler_config is a no-op."""
    aap_logger = logging.getLogger("aap")
    original_handlers = aap_logger.handlers[:]
    aap_logger.handlers = []

    try:
        cmd = MigrateCommand()
        cmd._configure_logging(str(tmp_path / "test.log"))

        migrate_logger = logging.getLogger(MIGRATE_LOGGER_NAME)
        assert migrate_logger.handlers[0].formatter is None
        assert migrate_logger.handlers[0].filters == []
        cmd._log_file_handle.close()
    finally:
        aap_logger.handlers = original_handlers
