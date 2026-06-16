import base64
import logging
from typing import Any, Tuple, Union

from django.conf import settings

from aap_gateway_api.models import ServiceCluster
from aap_gateway_api.utils.preferences import SettingNotSetException, TooManyPreferencesException, get_setting

logger = logging.getLogger("aap.gateway.proxy.service_auth")


class ServiceAuthHelper:
    # Mapping for pre-existing prefs/settings with non-standard naming
    custom_setting_map = {}

    @staticmethod
    def _get_pref_or_setting(name: str) -> Any:
        # Preference
        try:
            return get_setting(name, False)
        except (SettingNotSetException, TooManyPreferencesException):
            pass

        # Setting
        return getattr(settings, name, None)

    @staticmethod
    def _normalize_name(name: str) -> str:
        name = name.upper()

        # Custom naming
        name = ServiceAuthHelper.custom_setting_map[name] if name in ServiceAuthHelper.custom_setting_map else name
        return name

    @staticmethod
    def get_auth_header(service_type: str, auth_type: str) -> Union[Tuple[str, str], None]:
        """
        Creates envoy service auth header(s) based on service type and auth type.
        """
        # Look for preferences/settings
        match auth_type:
            case ServiceCluster.ServiceAuthType.TOKEN_AUTH:
                token_var = ServiceAuthHelper._normalize_name(f"{service_type}_TOKEN")
                token = ServiceAuthHelper._get_pref_or_setting(token_var)
                if not token:
                    raise NameError(f"{token_var} preference or setting not found.")

                return ("Authorization", f"Bearer {token}")
            case ServiceCluster.ServiceAuthType.BASIC_AUTH:
                username_var = ServiceAuthHelper._normalize_name(f"{service_type}_USERNAME")
                username = ServiceAuthHelper._get_pref_or_setting(username_var)

                password_var = ServiceAuthHelper._normalize_name(f"{service_type}_PASSWORD")
                password = ServiceAuthHelper._get_pref_or_setting(password_var)
                if not username or not password:
                    raise NameError(f"{username_var} and {password_var} preference or setting not set.")

                encoded_bytes = base64.b64encode(bytes(f"{username}:{password}", "utf-8"))
                encoded = encoded_bytes.decode('utf-8')
                return ("Authorization", f"Basic {encoded}")
            case _:
                raise RuntimeError(f"Invalid auth_type for service type {service_type}")
