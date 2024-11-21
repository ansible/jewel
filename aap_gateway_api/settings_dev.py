import logging
import sys
from os import getenv

DEBUG = True

# These lines are a hack to define LOGGING in this file so flake8 doesn't complain
LOGGING = {} if not LOGGING else LOGGING  # noqa: F821
INSTALLED_APPS = [] if not INSTALLED_APPS else INSTALLED_APPS  # noqa: F821

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

    LOGGING['handlers']['console']['()'] = ColorHandler

except ImportError as e:
    # logutils is only used for colored logs in the dev environment
    print(f"Failed library import, colors won't be in logs: {e}")


LOGGING['loggers']['aap']['level'] = "DEBUG"

INSTALLED_APPS.append('ansible_base.help_text_check')

ENABLE_DJANGO_DEBUG_TOOLBAR = False
if "test" not in sys.argv and getenv('DJANGO_DEBUG_TOOL_BAR', False):
    ENABLE_DJANGO_DEBUG_TOOLBAR = True

    try:
        INSTALLED_APPS  # noqa: F821
    except NameError:
        INSTALLED_APPS = []
    INSTALLED_APPS.append("debug_toolbar")

    try:
        MIDDLEWARE  # noqa: F821
    except NameError:
        MIDDLEWARE = []
    MIDDLEWARE = [
        "debug_toolbar.middleware.DebugToolbarMiddleware",
        *MIDDLEWARE,
    ]

    DEBUG_TOOLBAR_CONFIG = {
        'ENABLE_STACKTRACES': True,
        "SHOW_TOOLBAR_CALLBACK": lambda req: True,
    }
