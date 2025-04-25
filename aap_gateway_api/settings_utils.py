import logging
import os
import sys

from ansible_base.lib.dynamic_config import load_python_file_with_injected_context
from ansible_base.lib.utils.validation import to_python_boolean
from dynaconf import Dynaconf

logger = logging.getLogger('aap.gateway.settings.utils')
_GATEWAY_ETC_DIRECTORY = '/etc/ansible-automation-platform/gateway/'


def load_custom_envvars(settings):
    """Set settings from custom environment variables that are unprefixed.

    This function uses Dynaconf merging syntax.
    """
    data = {}

    if (DATABASE_ENGINE := os.getenv("DATABASE_ENGINE", None)) is not None:
        data["DATABASES__default__ENGINE"] = DATABASE_ENGINE
    if (DATABASE_NAME := os.getenv("DATABASE_NAME", None)) is not None:
        data["DATABASES__default__NAME"] = DATABASE_NAME
    if (DATABASE_USER := os.getenv("DATABASE_USER", None)) is not None:
        data["DATABASES__default__USER"] = DATABASE_USER
    if (DATABASE_PASSWORD := os.getenv("DATABASE_PASSWORD", None)) is not None:
        data["DATABASES__default__PASSWORD"] = DATABASE_PASSWORD
    if (DATABASE_HOST := os.getenv("DATABASE_HOST", None)) is not None:
        data["DATABASES__default__HOST"] = DATABASE_HOST
    if (DATABASE_PORT := os.getenv("DATABASE_PORT", None)) is not None:
        data["DATABASES__default__PORT"] = DATABASE_PORT
    if (ENVOY_HOSTNAME := os.getenv("ENVOY_HOSTNAME", None)) is not None:
        data["ENVOY_HOSTNAME"] = ENVOY_HOSTNAME
    if (ENVOY_VERIFY_HTTPS_CERTIFICATES := os.getenv("ENVOY_VERIFY_HTTPS_CERTIFICATES", None)) is not None:
        data["ENVOY_VERIFY_HTTPS_CERTIFICATES"] = ENVOY_VERIFY_HTTPS_CERTIFICATES
    if (ENVOY_PER_CONNECTION_BUFFER_LIMIT_BYTES := os.getenv("ENVOY_PER_CONNECTION_BUFFER_LIMIT_BYTES", None)) is not None:
        data["ENVOY_PER_CONNECTION_BUFFER_LIMIT_BYTES"] = ENVOY_PER_CONNECTION_BUFFER_LIMIT_BYTES
    if (GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH := os.getenv("GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH", None)) is not None:
        data["GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH"] = GRPC_SERVER_MAX_RECEIVE_MESSAGE_LENGTH
    if (GATEWAY_CERT_FILE := os.getenv("GATEWAY_CERT_FILE", None)) is not None:
        data["GATEWAY_CERT_FILE"] = GATEWAY_CERT_FILE
    if (GATEWAY_KEY_FILE := os.getenv("GATEWAY_KEY_FILE", None)) is not None:
        data["GATEWAY_KEY_FILE"] = GATEWAY_KEY_FILE
    if (GATEWAY_PATH_REWRITE_SCRIPT_FILE := os.getenv("GATEWAY_PATH_REWRITE_SCRIPT_FILE", None)) is not None:
        data["GATEWAY_PATH_REWRITE_SCRIPT_FILE"] = GATEWAY_PATH_REWRITE_SCRIPT_FILE
    if (REDIS_URL := os.getenv("REDIS_URL", None)) is not None:
        data["CACHES__primary__LOCATION"] = REDIS_URL
    if (CACHE_KEY_PREFIX := os.getenv("CACHE_KEY_PREFIX", None)) is not None:
        data["CACHES__primary__KEY_PREFIX"] = CACHE_KEY_PREFIX
    if (REDIS_TLS := os.getenv("REDIS_TLS", None)) is not None:
        data["CACHES__primary__OPTIONS__CLIENT_CLASS_KWARGS__ssl"] = to_python_boolean(REDIS_TLS)
    if (REDIS_MODE := os.getenv("REDIS_MODE", None)) is not None:
        data["CACHES__primary__OPTIONS__CLIENT_CLASS_KWARGS__mode"] = REDIS_MODE
    if (REDIS_SSL_CERT_REQS := os.getenv("REDIS_SSL_CERT_REQS", None)) is not None:
        data["CACHES__primary__OPTIONS__CLIENT_CLASS_KWARGS__ssl_cert_reqs"] = REDIS_SSL_CERT_REQS
    if (REDIS_HOSTS := os.getenv("REDIS_HOSTS", None)) is not None:
        data["CACHES__primary__OPTIONS__CLIENT_CLASS_KWARGS__redis_hosts"] = REDIS_HOSTS
    if (REDIS_KEY_FILE := os.getenv("REDIS_KEY_FILE", None)) is not None:
        data["CACHES__primary__OPTIONS__CLIENT_CLASS_KWARGS__ssl_keyfile"] = REDIS_KEY_FILE
    if (REDIS_CERT_FILE := os.getenv("REDIS_CERT_FILE", None)) is not None:
        data["CACHES__primary__OPTIONS__CLIENT_CLASS_KWARGS__ssl_certfile"] = REDIS_CERT_FILE
    if (REDIS_CA_CERT_FILE := os.getenv("REDIS_CA_CERT_FILE", None)) is not None:
        data["CACHES__primary__OPTIONS__CLIENT_CLASS_KWARGS__ssl_ca_certs"] = REDIS_CA_CERT_FILE
    if (FALLBACK_CACHE_FILE := os.getenv("FALLBACK_CACHE_FILE", None)) is not None:
        data["CACHES__fallback__LOCATION"] = FALLBACK_CACHE_FILE
    if (CSRF_TRUSTED_ORIGINS := os.getenv("CSRF_TRUSTED_ORIGINS", None)) is not None:
        data["CSRF_TRUSTED_ORIGINS"] = CSRF_TRUSTED_ORIGINS
    if (LOGOUT_ALLOWED_HOSTS := os.getenv("LOGOUT_ALLOWED_HOSTS", None)) is not None:
        data["LOGOUT_ALLOWED_HOSTS"] = LOGOUT_ALLOWED_HOSTS.split(",")
    if (PING_PAGE_CHECK_TIMEOUT := os.getenv("PING_PAGE_CHECK_TIMEOUT", None)) is not None:
        data["PING_PAGE_CHECK_TIMEOUT"] = PING_PAGE_CHECK_TIMEOUT
    if (PING_PAGE_CHECK_IGNORE_CERT := os.getenv("PING_PAGE_CHECK_IGNORE_CERT", None)) is not None:
        data["PING_PAGE_CHECK_IGNORE_CERT"] = to_python_boolean(PING_PAGE_CHECK_IGNORE_CERT)

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
