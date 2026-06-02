import logging
import os
import sys

from ansible_base.lib.dynamic_config import load_python_file_with_injected_context
from ansible_base.lib.utils.validation import to_python_boolean
from dynaconf import Dynaconf

logger = logging.getLogger('aap.gateway.settings.utils')
_GATEWAY_ETC_DIRECTORY = '/etc/ansible-automation-platform/gateway/'
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))


# Mapping of environment variables to Dynaconf settings keys.
# Each entry is (env_var_name, setting_key) or (env_var_name, setting_key, transform).
_CUSTOM_ENVVAR_MAPPINGS = (
    ("DATABASE_ENGINE", "DATABASES__default__ENGINE"),
    ("DATABASE_NAME", "DATABASES__default__NAME"),
    ("DATABASE_USER", "DATABASES__default__USER"),
    ("DATABASE_PASSWORD", "DATABASES__default__PASSWORD"),
    ("DATABASE_HOST", "DATABASES__default__HOST"),
    ("DATABASE_PORT", "DATABASES__default__PORT"),
    ("ENVOY_HOSTNAME", "ENVOY_HOSTNAME"),
    ("ENVOY_VERIFY_HTTPS_CERTIFICATES", "ENVOY_VERIFY_HTTPS_CERTIFICATES"),
    ("ENVOY_PER_CONNECTION_BUFFER_LIMIT_BYTES", "ENVOY_PER_CONNECTION_BUFFER_LIMIT_BYTES"),
    ("GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH", "GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH"),
    ("GATEWAY_CERT_FILE", "GATEWAY_CERT_FILE"),
    ("GATEWAY_KEY_FILE", "GATEWAY_KEY_FILE"),
    ("GATEWAY_PATH_REWRITE_SCRIPT_FILE", "GATEWAY_PATH_REWRITE_SCRIPT_FILE"),
    ("REDIS_URL", "CACHES__primary__LOCATION"),
    ("CACHE_KEY_PREFIX", "CACHES__primary__KEY_PREFIX"),
    ("REDIS_TLS", "CACHES__primary__OPTIONS__CLIENT_CLASS_KWARGS__ssl", to_python_boolean),
    ("REDIS_MODE", "CACHES__primary__OPTIONS__CLIENT_CLASS_KWARGS__mode"),
    ("REDIS_SSL_CERT_REQS", "CACHES__primary__OPTIONS__CLIENT_CLASS_KWARGS__ssl_cert_reqs"),
    ("REDIS_HOSTS", "CACHES__primary__OPTIONS__CLIENT_CLASS_KWARGS__redis_hosts"),
    ("REDIS_KEY_FILE", "CACHES__primary__OPTIONS__CLIENT_CLASS_KWARGS__ssl_keyfile"),
    ("REDIS_CERT_FILE", "CACHES__primary__OPTIONS__CLIENT_CLASS_KWARGS__ssl_certfile"),
    ("REDIS_CA_CERT_FILE", "CACHES__primary__OPTIONS__CLIENT_CLASS_KWARGS__ssl_ca_certs"),
    ("FALLBACK_CACHE_FILE", "CACHES__fallback__LOCATION"),
    ("CSRF_TRUSTED_ORIGINS", "CSRF_TRUSTED_ORIGINS"),
    ("LOGOUT_ALLOWED_HOSTS", "LOGOUT_ALLOWED_HOSTS", lambda v: v.split(",")),
    ("PING_PAGE_CHECK_TIMEOUT", "PING_PAGE_CHECK_TIMEOUT"),
    ("PING_PAGE_CHECK_IGNORE_CERT", "PING_PAGE_CHECK_IGNORE_CERT", to_python_boolean),
)


def load_custom_envvars(settings):
    """Set settings from custom environment variables that are unprefixed.

    This function uses Dynaconf merging syntax.
    """
    data = {}

    for entry in _CUSTOM_ENVVAR_MAPPINGS:
        env_var, setting_key = entry[0], entry[1]
        transform = entry[2] if len(entry) > 2 else None
        value = os.getenv(env_var)
        if value is not None:
            data[setting_key] = transform(value) if transform else value

    # override invalid settings
    if settings.GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH < settings.GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH_MIN_VALUE:
        sys.stderr.write(
            f"GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH was set lower than allowed minimum ({settings.GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH_MIN_VALUE}),"
            f" setting to {settings.GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH_MIN_VALUE}\n"
        )
        data["GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH"] = settings.GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH_MIN_VALUE

    settings.update(data, loader_identifier="settings:load_custom_envvars", merge=True)


def set_secret_key(settings):
    """Based on the value of GATEWAY_SECRET_KEY_FILE, set the SECRET_KEY setting."""

    settings.setdefault("SECRET_KEY_FILE", f'{_GATEWAY_ETC_DIRECTORY}/SECRET_KEY')

    # Make this unique, and don't share it with anybody.
    try:
        with open(settings.SECRET_KEY_FILE, 'rb') as f:
            settings.set("SECRET_KEY", f.read().strip(), loader_identifier="settings:set_secret_key")
    except FileNotFoundError:
        raise ImportError(f"Missing secret file {settings.SECRET_KEY_FILE}")
    except PermissionError:
        raise ImportError(f"Unable to read {settings.SECRET_KEY_FILE}")
    except Exception as e:
        raise ImportError(f"Unhandled exception when reading {settings.SECRET_KEY_FILE}, ({e.__class__}): {e}")


def load_grpc_settings(settings: Dynaconf) -> None:
    from sys import argv

    if 'start_grpc_server' not in argv:
        logger.debug('Not starting GRPC server, skipped loading GRPC settings')
        return

    logger.debug('Loading GRPC settings')

    settings.load_file("grpc_defaults.py")

    # Load settings for the GRPC server
    settings_file_path = os.environ.get('GATEWAY_GRPC_SETTINGS_FILE', f'{_GATEWAY_ETC_DIRECTORY}/grpc_settings.py')
    load_python_file_with_injected_context(settings_file_path, settings=settings)


def load_oidc_provider_settings(settings: Dynaconf) -> None:
    """Load OIDC provider settings.

    Loads OAuth2/OIDC provider configuration from oidc_provider.py,
    enabling Gateway to act as an OIDC Provider for authentication.
    """
    logger.debug('Loading OIDC provider settings')

    settings.load_file(os.path.join(_MODULE_DIR, "oidc_provider.py"))

    # Set OIDC issuer endpoint to FRONT_END_URL + /o
    # This ensures the issuer in OIDC discovery metadata is consistent regardless of
    # the Host header in the request, and matches the issuer used in workload identity tokens.
    front_end_url = settings.get('FRONT_END_URL', '')
    if front_end_url:
        settings.set('OAUTH2_PROVIDER__OIDC_ISS_ENDPOINT', f'{front_end_url}/o')
