"""
Controller fallback authenticator.

This fallback authenticator attempts to authenticate users against the Controller
service. If successful, it migrates the user's credentials to the gateway database.

This is used for migrating users from Controller to Gateway during the transition period.

Plugin Configuration:
    Module path: 'aap_gateway_api.authentication.fallbacks.controller'
    This module exports a FallbackAuthenticator class that handles Controller authentication.
"""

import logging
from typing import Optional
from urllib.parse import urljoin

import requests
from ansible_base.lib.utils.duration import convert_to_seconds
from ansible_base.lib.utils.settings import get_setting
from django.http import HttpRequest
from django.urls import reverse
from requests.auth import HTTPBasicAuth

from aap_gateway_api.models.service_api_route import ServiceAPIRoute
from aap_gateway_api.models.service_cluster import ServiceCluster
from aap_gateway_api.models.service_type import DefaultServiceType
from aap_gateway_api.models.user import User
from aap_gateway_api.utils.preferences import get_preference_value

logger = logging.getLogger('aap.gateway.authentication.fallbacks.controller')


class FallbackAuthenticator:
    """
    Fallback authenticator that validates users against the Controller service.

    This authenticator is used during the migration period when users may still
    have their passwords stored in Controller. If authentication succeeds against
    Controller, the user's password is migrated to the gateway database.

    Architecture:
        authenticate() [orchestrator]
        ├─→ _should_attempt_controller_auth() [preconditions & URL building]
        ├─→ _get_controller_user() [HTTP I/O]
        ├─→ _validate_controller_user_data() [validation: structure, LDAP, enterprise]
        └─→ [user migration logic]

    Authentication Flow:
        1. Check preconditions (request object, login path, user exists, etc.)
        2. Build Controller API URL dynamically from service configuration
        3. Make authenticated request to Controller /me/ endpoint
        4. Validate response structure (count, results)
        5. Check user type (reject LDAP/enterprise users)
        6. Migrate user data and password to Gateway
        7. Mark migration complete (use_controller_password = False)

    Safety Features:
        - Infinite loop prevention: Only attempts auth during gateway login requests
        - Dynamic URL construction: No hardcoded paths or URLs
        - Fail-fast validation: Preconditions checked before expensive operations
        - Comprehensive error handling: All network/parsing errors logged and handled
    """

    def authenticate(self, request: Optional[HttpRequest], username: str, password: str, **kwargs) -> Optional[User]:
        """
        Attempt to authenticate a user against the Controller service.

        If authentication succeeds and the user is a local (non-LDAP, non-enterprise) user,
        their password is migrated to the gateway database.

        Args:
            request: The HTTP request object (required for safety checks)
            username: The username to authenticate
            password: The password to authenticate
            **kwargs: Additional authentication parameters

        Returns:
            None (user was unable to be authenticated by Controller)
            User (user was authenticated by Controller, password migrated to Gateway)
        """
        # Check if we should attempt controller auth and get the controller URL
        gateway_user, controller_url = self._should_attempt_controller_auth(request, username)
        if not gateway_user or not controller_url:
            return None

        # Make API call to Controller to validate credentials (returns raw response dict)
        controller_response = self._get_controller_user(username, password, controller_url)
        if not controller_response:
            return None

        # Validate response structure and user data (checks for LDAP/enterprise users)
        controller_user_data = self._validate_controller_user_data(controller_response, username)
        if not controller_user_data:
            return None

        # User is valid, migrate their password and user data from Controller to Gateway
        logger.info(f"User '{username}' validated by Controller, migrating password and user data to Gateway.")

        # Migrate password and mark migration as complete
        gateway_user.set_password(password)
        gateway_user.use_controller_password = False
        gateway_user.save(update_fields=['password', 'use_controller_password'])

        logger.debug(f"Updated user '{gateway_user.username}' password in Gateway from Controller data")
        return gateway_user

    def _should_attempt_controller_auth(self, request: Optional[HttpRequest], username: str) -> tuple[Optional[User], Optional[str]]:
        """
        Check if we should attempt Controller fallback authentication and get the controller URL.

        Safety Check: To prevent infinite loops (proxy → gateway → controller → proxy → gateway),
        we only attempt Controller authentication when the request is to the gateway login endpoint.

        Args:
            request: The HTTP request object (needed for safety check)
            username: The username to authenticate

        Returns:
            Tuple of (gateway_user, controller_url) if all preconditions pass, (None, None) otherwise
        """
        # Safety check: Only attempt Controller fallback during gateway login to prevent infinite loops
        if not request:
            logger.debug("Controller authentication skipped: no request object")
            return (None, None)

        # We only want to try and call controller if we are the gateway login page.
        # Otherwise we will end up in an infinite loop.
        login_path = reverse('login')
        if not request.path.startswith(login_path):
            logger.debug(f"Controller authentication skipped: path '{request.path}' is not the gateway login endpoint ({login_path})")
            return (None, None)

        # Check if user exists and has the migration flag set
        try:
            gateway_user = User.objects.get(username=username)
            if not getattr(gateway_user, 'use_controller_password', False):
                logger.debug(f"Controller authentication skipped: user '{username}' does not have use_controller_password flag")
                return (None, None)
        except User.DoesNotExist:
            logger.debug(f"Controller authentication skipped: user '{username}' does not exist in Gateway")
            return (None, None)

        # Get controller base domain
        controller_base_domain = get_setting('gateway_proxy_url')
        # Its a misconfiguration if we don't have the gateway_proxy_url setting
        if not controller_base_domain:
            logger.error("Controller authentication failed: unable to get controller base domain from gateway_proxy_url setting")
            return (None, None)

        # Dynamically get the controller API path from the route configuration
        # If we don't have a controller service that is ok, we can just log an info message and return None
        controller_cluster = ServiceCluster.get_cluster_by_type(DefaultServiceType.CONTROLLER)
        if not controller_cluster:
            logger.info("Controller authentication failed: unable to find controller service cluster")
            return (None, None)

        # Since this is a ServiceAPIRoute, there really should never be more than one route for Controller
        # Its a misconfiguration if we have a controller instance but not an API route for it
        controller_route = ServiceAPIRoute.objects.filter(service_cluster=controller_cluster).first()
        if not controller_route:
            logger.error("Controller authentication failed: unable to find controller service API route")
            return (None, None)

        # Build the controller URL
        controller_api_path = controller_route.gateway_path.rstrip('/')
        controller_url = urljoin(controller_base_domain, f"{controller_api_path}/v2/me/")

        return (gateway_user, controller_url)

    def _validate_controller_user_data(self, response_data: dict, username: str) -> Optional[dict]:
        """
        Validate the response from the Controller /me/ endpoint and check user type.

        This method performs comprehensive validation:
        1. Validates response structure (count, results)
        2. Checks if user is an LDAP user (reject if ldap_dn is set)
        3. Checks if user is an enterprise user (reject if password != "$encrypted$")

        Args:
            response_data: The raw JSON response from Controller /me/ endpoint
            username: The username being authenticated (for logging)

        Returns:
            The controller user dictionary if valid and local user, None otherwise
        """
        # Validate response structure: Check if count exists and equals 1
        count = response_data.get("count")
        if count != 1:
            logger.warning(f"Unable to authenticate user '{username}' with Controller: response_data={response_data}")
            return None

        # Validate response structure: Check if results exists and is a non-empty list
        results = response_data.get("results")
        if not results or not isinstance(results, list) or len(results) == 0:
            logger.info(f"Unable to authenticate user '{username}' with Controller: invalid or empty results")
            return None

        if not isinstance(results[0], dict):
            logger.warning(f"Unable to authenticate user '{username}' with Controller: result is not a dictionary")
            return None

        user_data = results[0]

        # Validate user type: Check if user is an LDAP user (reject if ldap_dn is set)
        ldap_dn = user_data.get("ldap_dn")
        if ldap_dn is not None and ldap_dn != "":
            logger.warning(f"User '{username}' is an LDAP user and cannot be authenticated via Controller fallback.")
            return None

        # Validate user type: Check if user is an enterprise user (reject if password != "$encrypted$")
        if user_data.get('password', None) != "$encrypted$":
            logger.warning(f"User '{username}' is an enterprise user and cannot be authenticated via Controller fallback.")
            return None

        return user_data

    def _get_controller_user(self, username: str, password: str, controller_url: str) -> Optional[dict]:
        """
        Make a request to the Controller API /me/ endpoint to validate credentials.

        This method focuses solely on HTTP I/O and returns the raw response.
        Validation of the response structure and user data is handled separately.

        Args:
            username: The username to authenticate
            password: The password to authenticate
            controller_url: The full URL to the Controller /me/ endpoint

        Returns:
            Raw JSON response dict from Controller if HTTP request succeeds, None otherwise
        """
        # Get timeout setting
        timeout = convert_to_seconds(get_setting('GRPC_SERVER_AUTH_SERVICE_TIMEOUT'))

        # Make the API call to Controller
        try:
            logger.debug(f"Making API call to Controller: {controller_url}")
            response = requests.get(
                controller_url,
                auth=HTTPBasicAuth(username, password),
                timeout=int(timeout),
                verify=get_preference_value("proxy", "gateway_proxy_url_ignore_cert"),
            )
            logger.debug(f"Controller Response: {response.json()}")
            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError as http_err:
            logger.warning(f"Controller authentication HTTP error for user '{username}': {http_err}")
            return None
        except requests.exceptions.ConnectionError as conn_err:
            logger.warning(f"Controller authentication connection error for user '{username}': {conn_err}")
            return None
        except requests.exceptions.Timeout as timeout_err:
            logger.warning(f"Controller authentication timeout for user '{username}': {timeout_err}")
            return None
        except requests.exceptions.RequestException as err:
            logger.warning(f"Controller authentication request error for user '{username}': {err}")
            return None
        except ValueError as json_err:
            logger.warning(f"Controller authentication JSON decode error for user '{username}': {json_err}")
            return None
        except Exception as err:
            logger.error(f"Unexpected error during Controller authentication for user '{username}': {err}")
            return None
