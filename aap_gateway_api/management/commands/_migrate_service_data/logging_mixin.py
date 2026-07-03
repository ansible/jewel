import logging
from typing import Optional

logger = logging.getLogger('aap.gateway.management.commands.migrate_service_data')

# Progress reporting step size (percentage)
PROGRESS_STEP = 5


class LoggingMixin:
    @staticmethod
    def _copy_console_handler_config(handler: logging.Handler) -> None:
        """Copy formatter and filters from the 'aap' logger's console handler."""
        aap_handlers = logging.getLogger('aap').handlers
        if not aap_handlers:
            return
        console_handler = aap_handlers[0]
        if console_handler.formatter:
            handler.setFormatter(console_handler.formatter)
        for f in console_handler.filters:
            handler.addFilter(f)

    def _configure_logging(self, log_file: Optional[str]) -> None:
        """
        Configure the command's logger based on --log-file.

        When a log file path is provided, attaches a StreamHandler at INFO level
        so progress messages are written with structured formatting. When omitted,
        replaces all handlers with a NullHandler so logger calls are silently
        discarded and all output goes through self.stdout only.
        """
        for handler in logger.handlers[:]:
            handler.close()
        logger.handlers.clear()
        logger.propagate = False

        if hasattr(self, '_log_file_handle') and self._log_file_handle:
            self._log_file_handle.close()
            self._log_file_handle = None

        if log_file:
            self._log_file_handle = open(log_file, 'w')
            handler = logging.StreamHandler(self._log_file_handle)
            handler.setLevel(logging.INFO)
            self._copy_console_handler_config(handler)
            logger.addHandler(handler)
            if logger.level == logging.NOTSET or logger.level > logging.INFO:
                logger.setLevel(logging.INFO)
        else:
            logger.addHandler(logging.NullHandler())

    def _log(self, msg: str, level: int) -> None:
        """
        Write a message to both stdout (returned to the caller) and the logger
        (written to --log-file when provided).

        Stdout/stderr receives the message as-is (preserving newlines for
        terminal formatting). The logger receives each non-empty line as a
        separate log record so the formatter prefix appears on every line.
        """
        if level >= logging.WARNING:
            self.stderr.write(self.style.WARNING(msg))
        else:
            self.stdout.write(msg)
        for line in msg.split('\n'):
            if line:
                logger.log(level, line)

    def _log_progress(self, label: str, processed: int, total: int) -> None:
        """
        Report migration progress when a percentage threshold is crossed.

        Emits a message at every PROGRESS_STEP% interval. Always reports a starting
        message on the first item and a 100% message on the last item. If a single
        item crosses multiple thresholds, only the highest is reported.

        Output goes through _log(), which writes to both stdout and --log-file.
        """
        msg = None

        if total == 0:
            msg = f"Migration progress [{label}]: 0 items to process"
        else:
            percent = (processed / total) * 100
            threshold = (int(percent) // PROGRESS_STEP) * PROGRESS_STEP
            last = self._progress_thresholds.get(label, -1)

            if processed >= total:
                if last < 100:
                    self._progress_thresholds[label] = 100
                    msg = f"Migration progress [{label}]: {processed}/{total} (100%)"
            elif processed == 1 and last < 0:
                self._progress_thresholds[label] = threshold
                msg = f"Migration progress [{label}]: {processed}/{total} ({threshold}%)"
            else:
                threshold = min(threshold, 100)
                if threshold > last:
                    self._progress_thresholds[label] = threshold
                    msg = f"Migration progress [{label}]: {processed}/{total} ({threshold}%)"

        if msg:
            self._log(msg, logging.INFO)
