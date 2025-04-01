# This file uses dynaconf style of settings and it will be processed by dynaconf to handle merges and updates
import logging
import sys
from os import getenv

DEBUG = True

# show colored logs in the dev environment
try:
    import colorama
    from logutils.colorize import ColorizingStreamHandler

    colorama.deinit()
    colorama.init(wrap=False, convert=False, strip=False)

    class ColorHandler(ColorizingStreamHandler):
        def colorize(self, line, record):
            # comment out this method if you don't like the job_lifecycle
            # logs rendered with cyan text
            msg = super().colorize(line, record)
            return msg

        def format(self, record):
            message = logging.StreamHandler.format(self, record)
            return '\n'.join([self.colorize(line, record) for line in message.splitlines()])

        level_map = {
            logging.DEBUG: (None, 'green', True),
            logging.INFO: (None, None, True),
            logging.WARNING: (None, 'yellow', True),
            logging.ERROR: (None, 'red', True),
            logging.CRITICAL: (None, 'red', True),
        }

    LOGGING__handlers__console = '@merge {"()": "aap_gateway_api.settings_dev.ColorHandler"}'

except ImportError as e:
    # logutils is only used for colored logs in the dev environment
    print(f"Failed library import, colors won't be in logs: {e}")


LOGGING__loggers__aap__level = 'DEBUG'
_INSTALLED_APPS = "ansible_base.help_text_check"

ENABLE_DJANGO_DEBUG_TOOLBAR = False
if "test" not in sys.argv and getenv('DJANGO_DEBUG_TOOL_BAR', False):
    ENABLE_DJANGO_DEBUG_TOOLBAR = True

    _INSTALLED_APPS = f"{_INSTALLED_APPS},debug_toolbar"

    MIDDLEWARE = "@insert 0 debug_toolbar.middleware.DebugToolbarMiddleware"

    DEBUG_TOOLBAR_CONFIG = {
        'ENABLE_STACKTRACES': True,
        "SHOW_TOOLBAR_CALLBACK": lambda req: True,
    }

INSTALLED_APPS = f"@merge {_INSTALLED_APPS}"
PING_PAGE_CHECK_IGNORE_CERT = True


if getenv('SUPERVISOR_PROCESS_NAME') == "runserver":
    try:
        import debugpy

        debugpy.listen(("0.0.0.0", 3000))
        print('Debugpy attached to port 3000!')
    except ImportError:
        print("unable to enable debugpy, missing module")
    except RuntimeError as e:
        # If debugpy is already bound for whatever reason, we will get a RuntimeError with one of these messages.
        if "has already been called on this process" not in str(e) and "Address already in use" not in str(e):
            raise

    CSRF_TRUSTED_ORIGINS = ["https://localhost:8000"]
