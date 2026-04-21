import logging
import warnings

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugin
from ansible_base.authentication.models import Authenticator, AuthenticatorUser
from ansible_base.authentication.utils.user import can_user_change_password
from ansible_base.lib.serializers.common import CommonUserSerializer
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.policies import can_change_user
from crum import get_current_user
from django.contrib.auth import update_session_auth_hash
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import EmailValidator
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail
from rest_framework.fields import empty
from rest_framework.serializers import ValidationError

from aap_gateway_api.models import User
from aap_gateway_api.models.user import password_is_usable
from aap_gateway_api.utils import get_preference_value

logger = logging.getLogger('aap.gateway.serializer.user')

PASSWORD_DISABLED = 'Password Disabled'  # signal unusable passwords


@extend_schema_field({'type': 'object', 'additionalProperties': {'type': 'object', 'properties': {'uid': {'type': 'string'}, 'email': {'type': 'string'}}}})
class _AssociatedAuthenticatorsField(serializers.JSONField):
    """JSONField with OpenAPI schema annotation for associated_authenticators."""

    pass


@extend_schema_serializer(
    deprecate_fields=["authenticators", "authenticator_uid"],
)
class UserSerializer(CommonUserSerializer):
    password = serializers.CharField(required=False, max_length=128, allow_blank=True)
    authenticators = serializers.MultipleChoiceField(
        # If we load the authenticators here we end up with a static list of authenticators.
        # Instead, we will populate the authenticator choices in the __init__ method.
        choices=[],
        write_only=True,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text=_("DEPRECATED: This field is deprecated and will be removed in a future version. Please use 'associated_authenticators' instead."),
    )

    authenticator_uid = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        help_text=_("DEPRECATED: This field is deprecated and will be removed in a future version. Please use 'associated_authenticators' instead."),
    )
    associated_authenticators = _AssociatedAuthenticatorsField(write_only=True, required=False)

    last_login_from = serializers.SerializerMethodField(
        help_text=_(
            "Read-only field indicating the last authenticator used for successful login. "
            "Value is null if user has never logged in. This field is automatically updated "
            "on successful authentication. Cannot be set via API."
        )
    )

    is_platform_auditor = serializers.BooleanField(read_only=True)
    use_controller_password = serializers.BooleanField(required=False, read_only=True)

    def __init__(self, instance=None, data=empty, **kwargs):
        super().__init__(instance, data, **kwargs)

        self.fields['authenticators'].choices = list(Authenticator.objects.all().values_list('id', 'name').order_by('name'))
        # Track deprecation warnings to show only once per request
        self._deprecation_warnings = []

    class Meta(CommonUserSerializer.Meta):
        model = User
        fields = CommonUserSerializer.Meta.fields + [
            'username',
            'email',
            'first_name',
            'last_name',
            'last_login',
            'last_login_from',
            'password',
            'is_superuser',
            'is_platform_auditor',
            'authenticators',
            'authenticator_uid',
            'associated_authenticators',
            'managed',
            "use_controller_password",
        ]
        read_only_fields = ["last_login", "is_platform_auditor", "use_controller_password", "last_login_from"]

    def _add_deprecation_warning(self, field_name, message):
        """Add a deprecation warning for a field if not already added."""
        if field_name not in [w.get('field') for w in self._deprecation_warnings]:
            self._deprecation_warnings.append({'field': field_name, 'message': message})
            warnings.warn(message, DeprecationWarning, stacklevel=2)
            logger.warning(f"Deprecation warning for field '{field_name}': {message}")

    def _collect_validation_errors(self, validation_functions):
        """
        Common helper to collect validation errors from multiple validation functions.

        Args:
            validation_functions: List of tuples (function, args, kwargs) to call for validation

        Returns:
            List of error messages
        """
        errors = []
        for func, args, kwargs in validation_functions:
            try:
                func(*args, **kwargs)
            except ValidationError as e:
                if isinstance(e.detail, list):
                    errors.extend(e.detail)
                else:
                    errors.append(e.detail)
        return errors

    def _validate_authenticator_exists(self, authenticator_id):
        """Validate that an authenticator exists and return it."""
        try:
            return Authenticator.objects.get(id=authenticator_id)
        except Authenticator.DoesNotExist:
            raise ValidationError(f"Authenticator with ID {authenticator_id} does not exist")

    def _check_uid_conflict(self, authenticator, uid, user_instance=None):
        """Check if a UID conflicts with an existing user for the given authenticator."""
        existing_auth_user = AuthenticatorUser.objects.filter(provider=authenticator, uid=uid).exclude(user=user_instance).first()

        if existing_auth_user:
            return {
                'conflicting_user': existing_auth_user.user.username,
                'error_message': f"UID '{uid}' is already in use for authenticator '{authenticator.name}' by user '{existing_auth_user.user.username}'",
            }
        return None

    def _create_authenticator_user(self, authenticator_id, uid, user_instance, email=None):
        """Create an AuthenticatorUser with proper UID handling and logging."""
        authenticator = self._validate_authenticator_exists(authenticator_id)

        # Check for conflicts before creating
        conflict = self._check_uid_conflict(authenticator, uid, user_instance)
        if conflict:
            raise ValidationError(conflict['error_message'])

        logger.info(f"Adding authenticator {authenticator.name} with UID {uid} for user {user_instance.username}")

        auth_type = get_authenticator_plugin(authenticator.type).type

        # For local authenticators, UID must match the username
        if auth_type == 'local' and uid != user_instance.username:
            logger.info(
                f"Creating new user {user_instance.username} with authenticator_uid {user_instance.username} for the local authenticator {authenticator.name}; "
                "uid must match username for local authenticator users"
            )
            uid = user_instance.username

        # Set email on user instance if provided (all authenticators for a user share the same email)
        # Only set email if it's not already set
        if email is not None and user_instance.email is None:
            user_instance.email = email

        AuthenticatorUser.objects.create(uid=uid, user=user_instance, provider=authenticator, email=email)
        return authenticator

    def _get_requesting_user(self):
        request = self.context.get('request', None)
        if request and hasattr(request, 'user'):
            return request.user
        return None

    def is_superuser_making_request(self) -> bool:
        user = self._get_requesting_user()
        return user is not None and user.is_superuser

    def validate_password(self, value: str) -> str:
        if not value or value in [ENCRYPTED_STRING, PASSWORD_DISABLED]:
            return value

        user_instance = self.instance  # This will be None for creation

        if user_instance and not can_user_change_password(user_instance):
            raise ValidationError(_('Password can not be set for this user'))

        errors = self._perform_password_validation(value)
        if errors and not self._allow_insecure_password_override():
            raise ValidationError(errors)

        # Proceed if password passes all checks, or if an insecure password is allowed by superuser
        return value

    def _perform_password_validation(self, password: str) -> list:
        errors = []
        password_min_length = get_preference_value('local_login', 'password_min_length')
        password_min_digits = get_preference_value('local_login', 'password_min_digits')
        password_min_upper = get_preference_value('local_login', 'password_min_upper')
        password_min_special = get_preference_value('local_login', 'password_min_special')
        if password_min_length > 0 and len(password) < password_min_length:
            errors.append(_('Password must be at least {} characters long.'.format(password_min_length)))
        if password_min_digits > 0 and sum(c.isdigit() for c in password) < password_min_digits:
            errors.append(_('Password must contain at least {} digits.'.format(password_min_digits)))
        if password_min_upper > 0 and sum(c.isupper() for c in password) < password_min_upper:
            errors.append(_('Password must contain at least {} uppercase characters.'.format(password_min_upper)))
        if password_min_special > 0 and sum(not c.isalnum() for c in password) < password_min_special:
            errors.append(_('Password must contain at least {} special characters.'.format(password_min_special)))
        return errors

    def _allow_insecure_password_override(self) -> bool:
        if self.is_superuser_making_request() and get_preference_value('local_login', 'allow_admins_to_set_insecure'):
            user = get_current_user()
            username = self.initial_data.get('username', None)
            if username is None:
                if self.instance is None:
                    raise ValidationError(_("Either username needs to be present or we need an active instance"))
                username = self.instance.username
            logger.warning(f"User {user.username} was allowed to save an insecure password for user {username}")
            return True
        return False

    def _get_last_login_authenticator(self, user_instance):
        """Get the authenticator from last_login_from or the single authenticator if user has only one."""
        if not user_instance:
            return None

        return user_instance.last_login_from

    def validate_authenticator_uid(self, value: str) -> str:
        """
        Validate authenticator_uid field with deprecation warning and enhanced backward compatibility.
        """
        if value is not None and "authenticator_uid" in self.initial_data:
            self._add_deprecation_warning(
                "authenticator_uid",
                "The 'authenticator_uid' field is deprecated and will be removed in a future version. "
                "Use 'associated_authenticators' field instead to specify UIDs per authenticator.",
            )

        user_instance = self.instance  # This will be None for creation

        if user_instance is None:
            # no validation needed upon user creation
            return value

        # if there is an active user instance, we are performing an update on existing authenticator_uid
        current_uids = user_instance.get_authenticator_uids()

        # if only one (or zero) authenticator, allow change
        if len(current_uids) <= 1:
            return value

        if value and not self._is_authenticator_uid_unchanged(value, current_uids):
            # Disallow UID changes for users with multiple authenticators to prevent ambiguity and data loss.
            # Future improvements could include:
            # - Setting all authenticators to a single UID
            # - Updating specific authenticator UIDs
            # - Adding an endpoint for managing multiple authenticators
            self._add_deprecation_warning(
                "authenticator_uid_ambiguous",
                "UID changes for users with multiple authenticators are ambiguous. "
                "The update will be applied to the authenticator from 'last_login_from' if available. "
                "Use 'associated_authenticators' for precise control.",
            )

        # For backward compatibility, allow authenticator_uid to be used when authenticators field is also present
        if "authenticators" in self.initial_data and value:
            # When both deprecated fields are used together, allow the operation
            return value

        # New behavior: authenticator_uid applies only to the authenticator from last_login_from
        target_authenticator = self._get_last_login_authenticator(user_instance)
        if not target_authenticator and value:
            # Be more permissive for backward compatibility - only warn, don't fail
            self._add_deprecation_warning(
                "authenticator_uid_no_target",
                "Cannot determine target authenticator for authenticator_uid update. Consider using 'associated_authenticators' field for precise control.",
            )

        return value

    def _is_authenticator_uid_unchanged(self, value: str, current_uids: list[str]) -> bool:
        incoming_values = {uid.strip() for uid in value.split(',') if uid.strip()}
        return incoming_values == set(current_uids)

    def validate_authenticators(self, value):
        """
        Perform permissive validation for the 'authenticators' field.

        This validation is intentionally permissive and focuses on basic scenarios
        to support backward compatibility with a deprecated field. It allows the value
        to pass through, deferring more complex validation to the cross-field
        `validate` method, which can assess the overall validity of the request.

        The key responsibilities of this method are:
        1. Add a deprecation warning if the 'authenticators' field is used.
        2. Return the value to allow the validation process to continue, where
           cross-field validation will handle more complex cases.

        Note: The restriction of authenticator modifications to superusers is
        enforced at the view level.
        """
        if value is not None and "authenticators" in self.initial_data:
            self._add_deprecation_warning(
                "authenticators",
                "The 'authenticators' field is deprecated and will be removed in a future version. "
                "Use 'associated_authenticators' field instead for full control over multiple authenticators.",
            )

        # Let cross-field validation handle all other scenarios
        return value

    def stringify_dict_keys(self, data):
        """
        Recursively converts all dictionary keys in a nested structure to strings.
        """
        if isinstance(data, dict):
            return {str(k): self.stringify_dict_keys(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self.stringify_dict_keys(item) for item in data]
        return data

    def validate_associated_authenticators(self, value):
        """
        Validate the associated_authenticators field by coordinating helper validations.
        """
        if not value:
            return {}

        if self.instance:
            existing_authenticators = self.instance.get_associated_authenticators() or {}
            normalized_existing = self.stringify_dict_keys(existing_authenticators)
            normalized_submitted = self.stringify_dict_keys(value)

            # If fields are the same, we can return early
            if normalized_existing == normalized_submitted:
                return value

        if not self.is_superuser_making_request():
            raise serializers.ValidationError(_("Only superusers can manage associated_authenticators using this field."))

        if not isinstance(value, dict):
            raise serializers.ValidationError(_("This field must be a JSON object (dictionary)."))

        # Use the common validation error collection pattern
        validation_functions = [
            (self._validate_authenticator_keys_exist, (value.keys(),), {}),
            (self._validate_authenticator_details_format, (value,), {}),
            (self._validate_associated_authenticators_conflicts, (value, self.instance), {}),
        ]

        errors = self._collect_validation_errors(validation_functions)
        if errors:
            raise serializers.ValidationError(errors)

        return value

    def _validate_authenticator_keys_exist(self, keys):
        """Ensure all authenticator IDs are valid integers that exist in the database."""
        try:
            authenticator_ids = [int(key) for key in keys]
        except (ValueError, TypeError):
            raise serializers.ValidationError(_("All authenticator IDs (the keys) must be valid integers."))

        existing_ids = set(Authenticator.objects.filter(id__in=authenticator_ids).values_list('id', flat=True))
        non_existent_ids = set(authenticator_ids) - existing_ids

        if non_existent_ids:
            error_message = _("The following authenticator IDs do not exist: {ids}").format(ids=", ".join(map(str, sorted(non_existent_ids))))
            raise serializers.ValidationError(error_message)

    def _validate_authenticator_details_format(self, value):
        """Validate the format of each authenticator's details dictionary."""
        errors = []
        validate_email = EmailValidator()
        # Define the set of valid keys for each authenticator's details.
        allowed_keys = {'uid', 'email'}

        for auth_id, details in value.items():
            if not isinstance(details, dict):
                errors.append(_("The value for key '{auth_id}' must be a dictionary.").format(auth_id=auth_id))
                continue  # Move to next item if format is wrong

            unknown_keys = set(details.keys()) - allowed_keys
            if unknown_keys:
                # Format the unknown keys for a clear error message.
                keys_str = ", ".join(sorted(unknown_keys))
                errors.append(
                    _("Unknown key(s) for authenticator '{auth_id}': {keys_str}. Only 'uid' and 'email' are allowed.").format(
                        auth_id=auth_id, keys_str=keys_str
                    )
                )

            # Check for mandatory 'uid'
            if not isinstance(details.get('uid'), str) or not details.get('uid'):
                errors.append(_("Each authenticator must have a non-empty 'uid' string. Error at key '{auth_id}'.").format(auth_id=auth_id))

            # Check optional 'email'
            if 'email' in details and details['email'] is not None:
                email = details['email']
                if not isinstance(email, str):
                    errors.append(_("The 'email' for authenticator '{auth_id}' must be a string or null.").format(auth_id=auth_id))
                else:
                    try:
                        validate_email(email)
                    except DjangoValidationError:
                        errors.append(_("The email '{email}' for authenticator '{auth_id}' is not a valid email address.").format(email=email, auth_id=auth_id))

        if errors:
            raise serializers.ValidationError(errors)

    def _validate_email_change(self, data):
        """Prevent unauthorized changes to email.

        Delegates to DAB's can_change_user with can_self_edit=False so that
        only superusers and org admins (who administer ALL of the target
        user's organizations) may change email.
        """
        if self.instance is None:
            return

        if 'email' not in data or data['email'] == self.instance.email:
            return

        requesting_user = self._get_requesting_user()
        if requesting_user is None:
            logger.debug("Skipping email change authorization: no requesting user in context (system sync path)")
            return

        if not can_change_user(requesting_user, self.instance, can_self_edit=False):
            raise ValidationError({'email': [_("You do not have permission to change the %(field)s field.") % {'field': 'email'}]})

    def validate(self, data):
        """
        Perform cross-field validation for authenticators and authenticator_uid.

        This method:
        1. Delegates to DAB's CommonUserSerializer.validate() for system user
           protection and email change authorization (first line of defense).
        2. Applies Gateway-local email policy via _validate_email_change as
           a second line of defense (defense-in-depth).
        3. Handles partial updates for authenticator_uid.
        4. Validates authenticator and UID combinations:
           - Ensures UID is present when adding/modifying authenticators.
           - Checks for UID conflicts across authenticators.
           - Validates new authenticators for conflicts.
        5. Ensures authenticator_uid is empty when removing all authenticators.

        Raises ValidationError if any validation fails.
        """
        data = super().validate(data)
        self._validate_email_change(data)

        authenticators = data.get('authenticators')
        authenticator_uid = data.get('authenticator_uid')

        user_instance = self.instance  # This will be None for creation
        current_authenticators = user_instance.get_authenticator_ids() if user_instance else []

        # Check if we're adding authenticators without providing UID (only for specific scenarios)
        # Skip this validation if associated_authenticators is present (new field takes precedence)
        if authenticators is not None and user_instance and 'associated_authenticators' not in self.initial_data:
            authenticators_to_add = set(authenticators) - set(current_authenticators)
            authenticators_to_remove = set(current_authenticators) - set(authenticators)
            # Only require UID when adding new authenticators to existing ones (not when replacing or removing)
            if authenticators_to_add and not authenticators_to_remove and not authenticator_uid:
                # For now, allow it to proceed but add a warning - backward compatibility
                self._add_deprecation_warning(
                    "authenticator_uid_missing",
                    "When adding new authenticators using the deprecated 'authenticators' field, "
                    "the 'authenticator_uid' field should be provided for best results.",
                )

        self._handle_partial_update(data, user_instance)

        errors = {}
        # Skip deprecated field validation when associated_authenticators is present (new field takes precedence)
        if 'associated_authenticators' not in self.initial_data:
            if authenticators:
                self._validate_authenticators_and_uid(authenticators, authenticator_uid, user_instance, current_authenticators, errors)

            self._validate_empty_authenticators(authenticators, authenticator_uid, errors)

            if errors:
                raise ValidationError(errors)

        return data

    def _handle_partial_update(self, data, user_instance):
        if self.partial and 'authenticators' in self.initial_data:
            # Default to current authenticator_uid if not provided
            if 'authenticator_uid' not in self.initial_data and user_instance:
                data['authenticator_uid'] = user_instance.get_authenticator_uids()[0]

    def _validate_authenticators_and_uid(self, authenticators, authenticator_uid, user_instance, current_authenticators, errors):
        # Skip UID validation if we're only removing authenticators
        if not self._is_only_removing_authenticators(authenticators, current_authenticators):
            authenticators_to_add = set(authenticators) - set(current_authenticators)
            authenticators_to_remove = set(current_authenticators) - set(authenticators)

            # Treat empty string as no UID
            if authenticator_uid == '':
                authenticator_uid = None

            # For user creation, always require authenticator_uid if authenticators are specified
            if authenticators and not authenticator_uid:
                errors.setdefault('authenticator_uid', []).append(
                    ErrorDetail(_("Authenticator UID cannot be empty when setting authenticators."), code='required')
                )

            # For user updates, only require UID when adding new authenticators to a user with existing authenticators
            if user_instance and len(authenticators_to_add) > 0 and not authenticators_to_remove:
                # This is adding new authenticators to existing ones
                if len(current_authenticators) > 0:
                    self._validate_uid_presence(authenticator_uid, authenticators, errors)

            # Check for conflicts when UID is provided
            self._validate_uid_conflicts(authenticators, authenticator_uid, user_instance, errors)

            # Check for specific scenarios that should fail
            self._validate_new_authenticators(authenticators, authenticator_uid, user_instance, current_authenticators, errors)

    def _is_only_removing_authenticators(self, authenticators, current_authenticators):
        return set(authenticators) < set(current_authenticators)

    def _validate_uid_presence(self, authenticator_uid, authenticators, errors):
        # For deprecated fields, we need to check if adding new authenticators requires a UID
        # Only require UID when adding new authenticators, not for other operations
        if not authenticator_uid:
            errors.setdefault('authenticator_uid', []).append(
                ErrorDetail(_("When adding new authenticators, the 'authenticator_uid' field must be provided."), code='required')
            )

    def _validate_uid_conflicts(self, authenticators, authenticator_uid, user_instance, errors):
        # For deprecated fields, still need to check for conflicts
        if authenticator_uid:
            for authenticator_id in authenticators:
                try:
                    authenticator = self._validate_authenticator_exists(authenticator_id)
                    conflict = self._check_uid_conflict(authenticator, authenticator_uid, user_instance)
                    if conflict:
                        errors.setdefault('authenticator_uid', []).append(
                            ErrorDetail(_(f"UID '{authenticator_uid}' is already in use for authenticator: {authenticator.name}"), code='uid_conflict')
                        )
                        errors.setdefault('authenticators', []).append(
                            ErrorDetail(_(f"Cannot set authenticator '{authenticator.name}': {conflict['error_message']}"), code='uid_conflict')
                        )
                except ValidationError:
                    continue

    def _validate_new_authenticators(self, authenticators, authenticator_uid, user_instance, current_authenticators, errors):
        # For deprecated fields, validate specific scenarios that should fail
        if user_instance and authenticators != current_authenticators:
            authenticators_to_add = set(authenticators) - set(current_authenticators)
            authenticators_to_remove = set(current_authenticators) - set(authenticators)

            # If the result would have multiple authenticators, treat it as "multiple new authenticators"
            if len(authenticators) > 1:
                errors.setdefault('authenticators', []).append(
                    ErrorDetail(
                        _(
                            "Adding multiple new authenticators is not supported "
                            "with the 'authenticators' field. Use 'associated_authenticators' field to manage multiple authenticators."
                        ),
                        code='multiple_new_authenticators',
                    )
                )

            # Adding to existing authenticators when result would be single: allow this case
            elif len(authenticators_to_add) >= 1 and not authenticators_to_remove and len(authenticators) == 1:
                # This is replacing existing authenticator with a single new one - should be allowed
                pass

    def _validate_empty_authenticators(self, authenticators, authenticator_uid, errors):
        if authenticators is not None and len(authenticators) == 0 and authenticator_uid:
            errors.setdefault('authenticator_uid', []).append(
                ErrorDetail(_("Authenticator UID should be empty when removing all authenticators."), code='invalid')
            )

    def _remove_authenticators(self, authenticators_to_remove, user_instance):
        """
        Remove specified authenticators from the user and log each removal action.
        """
        for remove_authenticator_id in authenticators_to_remove:
            logger.debug(f"Deleting authenticator {remove_authenticator_id} from {user_instance.username}")
            user_instance.authenticator_users.filter(provider__id=remove_authenticator_id).delete()

        logger.info(f"Removed authenticators: {list(authenticators_to_remove)}")

    def _add_authenticators(self, authenticators_to_add, authenticator_uid, user_instance, email=None):
        """
        Add new authenticators to the user, create AuthenticatorUser objects, and log the additions.
        """
        for add_authenticator_id in authenticators_to_add:
            self._create_authenticator_user(add_authenticator_id, authenticator_uid, user_instance, email)

        logger.info(f"Added authenticators: {authenticators_to_add}")

    def _update_authenticator_uids(self, authenticator_uid, user_instance):
        """
        Update UIDs for all authenticators of the user, logging each update.
        For local authenticators, ensure UID matches the username.
        For non-local authenticators, update UID to the provided authenticator_uid.
        """
        new_username = user_instance.username  # This will be the new username if it was changed
        existing_authenticator_uid = user_instance.get_authenticator_uids()

        if authenticator_uid is None or authenticator_uid in existing_authenticator_uid:
            # Still need to update local authenticators to match username even if no UID change requested
            for authenticator_user in user_instance.authenticator_users.all():
                auth_type = get_authenticator_plugin(authenticator_user.provider.type).type
                if auth_type == 'local' and authenticator_user.uid != new_username:
                    logger.info(
                        f"Auto-correcting local authenticator UID from {authenticator_user.uid} to {new_username} "
                        f"for user {new_username} on {authenticator_user.provider.name}"
                    )
                    authenticator_user.uid = new_username
                    authenticator_user.save(update_fields=['uid'])
            return  # No other updates needed

        for authenticator_user in user_instance.authenticator_users.all():
            auth_type = get_authenticator_plugin(authenticator_user.provider.type).type

            if auth_type == 'local':
                # For local authenticators, UID must match the username
                new_uid = new_username
                if new_username != authenticator_uid:
                    logger.info(
                        f"Setting authenticator_uid to {new_username} for user {new_username} "
                        f"for the local authenticator {authenticator_user.provider.name}; uid must match username for local authenticator users."
                    )
            else:
                new_uid = authenticator_uid

            logger.debug(
                f"Updating UID to {new_uid} for user {new_username} (old username: {authenticator_user.user.username}) on {authenticator_user.provider.name}"
            )

            authenticator_user.uid = new_uid
            authenticator_user.save(update_fields=['uid'])

        logger.info(f"Updated authenticator UID to {authenticator_uid}")

    def _update_users_authenticators(self, authenticators, authenticator_uid, associated_authenticators, user_instance):
        """
        Update user's authenticators with proper processing order:
        1. Process legacy fields first (authenticators and authenticator_uid)
        2. Then process new field (associated_authenticators) to give it priority
        Log all actions performed.
        """
        logger.info(f"Updating authenticators for user {user_instance.username}")

        existing_authenticators = user_instance.get_authenticator_ids()

        # Process legacy fields first for backward compatibility
        if authenticators is not None or authenticator_uid is not None:
            self._process_legacy_authenticator_fields(
                authenticators,
                authenticator_uid,
                user_instance,
                existing_authenticators,
            )

        # Then process new field, giving it priority over legacy fields
        if "associated_authenticators" in self.initial_data and associated_authenticators is not None:
            self._process_associated_authenticators_field(associated_authenticators, user_instance)

        logger.info(f"Successfully updated authenticators for user {user_instance.username}")

    def _process_legacy_authenticator_fields(self, authenticators, authenticator_uid, user_instance, existing_authenticators):
        """Process the legacy authenticators and authenticator_uid fields."""
        if authenticators is not None:
            # When authenticators is explicitly set to empty list, remove ALL authenticators
            if len(authenticators) == 0:
                # Remove all authenticators unconditionally
                user_instance.authenticator_users.all().delete()
                # Force refresh the user instance to clear any cached QuerySet results
                user_instance.refresh_from_db()
                logger.info("Removed all authenticators as requested")
            else:
                # Normal add/remove logic for non-empty authenticators list
                authenticators_to_remove = set(existing_authenticators) - set(authenticators)
                authenticators_to_add = set(authenticators) - set(existing_authenticators)

                self._remove_authenticators(authenticators_to_remove, user_instance)
                self._add_authenticators(authenticators_to_add, authenticator_uid, user_instance)
                self._update_authenticator_uids(authenticator_uid, user_instance)

        # Handle authenticator_uid updates for the target authenticator
        elif authenticator_uid is not None:
            self._update_legacy_authenticator_uid(authenticator_uid, user_instance)

    def _update_legacy_authenticator_uid(self, authenticator_uid, user_instance):
        """Update UID for the target authenticator (from last_login_from or single authenticator)."""
        # Check if user has multiple authenticators and generate warning
        authenticators = list(user_instance.authenticator_users.all())
        if len(authenticators) > 1:
            self._add_deprecation_warning(
                "authenticator_uid_multiple",
                "Updating 'authenticator_uid' for a user with multiple authenticators. "
                "The change will be applied to the authenticator from 'last_login_from' if available. "
                "Consider using 'associated_authenticators' instead for precise control.",
            )

        target_authenticator = self._get_last_login_authenticator(user_instance)
        if not target_authenticator:
            logger.warning(f"Cannot update authenticator_uid for user {user_instance.username}: no target authenticator found")
            return

        # Find the AuthenticatorUser for the target authenticator
        try:
            auth_user = user_instance.authenticator_users.get(provider=target_authenticator)

            # For local authenticators, UID must match username
            auth_type = get_authenticator_plugin(target_authenticator.type).type
            if auth_type == 'local':
                corrected_uid = user_instance.username
                if auth_user.uid != corrected_uid:
                    logger.info(
                        f"Correcting local authenticator UID from {auth_user.uid} to {corrected_uid} "
                        f"for user {user_instance.username} on authenticator {target_authenticator.name}"
                    )
                    auth_user.uid = corrected_uid
                    auth_user.save(update_fields=["uid"])
            else:
                # For non-local authenticators, use the provided UID
                if auth_user.uid != authenticator_uid:
                    auth_user.uid = authenticator_uid
                    auth_user.save(update_fields=["uid"])
                    logger.info(f"Updated UID to {authenticator_uid} for user {user_instance.username} on authenticator {target_authenticator.name}")
        except AuthenticatorUser.DoesNotExist:
            logger.warning(f"No AuthenticatorUser found for user {user_instance.username} and authenticator {target_authenticator.name}")

    def _validate_associated_authenticators_conflicts(self, associated_authenticators, user_instance):
        """Validate UID conflicts for the associated_authenticators field."""
        errors = []

        for auth_id_str, data in associated_authenticators.items():
            specific_uid = data.get("uid")
            if not specific_uid:
                continue

            try:
                authenticator = self._validate_authenticator_exists(int(auth_id_str))
                conflict = self._check_uid_conflict(authenticator, specific_uid, user_instance)
                if conflict:
                    errors.append(conflict['error_message'])
            except ValidationError:
                continue  # This will be caught by field validation

        if errors:
            raise serializers.ValidationError({"associated_authenticators": errors})

    def _process_associated_authenticators_field(self, associated_authenticators, user_instance):
        """Process the new associated_authenticators field."""
        # Validate conflicts before making changes
        self._validate_associated_authenticators_conflicts(associated_authenticators, user_instance)

        # Remove all existing authenticators first
        existing_authenticators = user_instance.get_authenticator_ids()
        if existing_authenticators:
            self._remove_authenticators(existing_authenticators, user_instance)

        # Find the email from any authenticator (they should all have the same email for the user)
        user_email = None
        for auth_id_str, data in associated_authenticators.items():
            if data.get("email") is not None:
                user_email = data.get("email")
                break

        # Set the email on the user instance once if any authenticator has an email
        if user_email is not None:
            user_instance.email = user_email
            user_instance.save(update_fields=['email'])

        # Add new authenticators from associated_authenticators
        for auth_id_str, data in associated_authenticators.items():
            specific_uid = data.get("uid")
            email = data.get("email")
            if specific_uid is not None:
                self._add_authenticator_from_associated_field(int(auth_id_str), specific_uid, user_instance, email=email)
                # Don't call _update_authenticator_uids here as it auto-corrects local authenticators
                # The associated_authenticators field should preserve explicitly set UIDs

    def _add_authenticator_from_associated_field(self, authenticator_id, uid, user_instance, email=None):
        """Add authenticator from associated_authenticators field, preserving explicitly set UIDs."""
        try:
            authenticator = self._create_authenticator_user(authenticator_id, uid, user_instance, email=email)
            logger.info(f"Added authenticator {authenticator.name} with UID {uid}")
        except ValidationError as e:
            # For local authenticators, auto-correct the UID to match username
            auth_type = get_authenticator_plugin(Authenticator.objects.get(id=authenticator_id).type).type
            if auth_type == 'local' and uid != user_instance.username:
                logger.warning(f"Local authenticator UID '{uid}' does not match username '{user_instance.username}', correcting to username")
                self._create_authenticator_user(authenticator_id, user_instance.username, user_instance, email=email)
            else:
                raise e

    @transaction.atomic
    def update(self, instance, validated_data):
        """
        Update user instance:
        1. Handle password changes (removing encrypted strings)
        2. Process username changes, updating related authenticator information
        3. Update authenticators and UIDs
        Wrapped in a database transaction for atomicity.
        """
        # We don't want the $encrypted$ password going back to the model
        if validated_data.get('password', "") in [ENCRYPTED_STRING, PASSWORD_DISABLED]:
            validated_data.pop('password', None)
        old_username = instance.username
        new_username = validated_data.get('username', old_username)

        if old_username != new_username:
            # Handle username change, updating related authenticator information
            validated_data['username'] = new_username
            instance.username = new_username
            # Only update local authenticator UIDs automatically if not using the new field
            # The new associated_authenticators field should preserve explicitly set UIDs
            if "associated_authenticators" not in self.initial_data:
                # We're in @transaction.atomic, so we don't risk uid getting out of sync here.
                instance.update_local_authenticator_uid_from_username()

        # Remove the authenticators field since thats not a real field on the User model
        authenticators = validated_data.pop('authenticators', None)
        authenticator_uid = validated_data.pop('authenticator_uid', None)
        associated_authenticators = validated_data.pop('associated_authenticators', None)

        # Handle authenticator changes
        self._update_users_authenticators(authenticators, authenticator_uid, associated_authenticators, instance)
        # Update the User model with validated data
        instance = super().update(instance, validated_data)
        # Refresh the instance from the database to ensure the response reflects any authenticator UID corrections
        instance.refresh_from_db()
        # Also clear the cached related objects to ensure fresh data
        if hasattr(instance, '_prefetched_objects_cache'):
            instance._prefetched_objects_cache = {}

        # If we are updating a password we need to reset the session or the user will be logged out
        if validated_data.get('password', None) and self.context['request'].user.username == instance.username:
            update_session_auth_hash(self.context['request'], instance)

        return instance

    @transaction.atomic
    def create(self, validated_data):
        """
        Create a new User instance and associate it with provided authenticators.
        Wrapped in a database transaction for atomicity.
        """
        # Remove the authenticators field since thats not a real field on the User model
        authenticators = validated_data.pop('authenticators', None)
        authenticator_uid = validated_data.pop('authenticator_uid', None)
        associated_authenticators = validated_data.pop('associated_authenticators', None)

        # Create the User instance
        new_user = super().create(validated_data)

        # Associate authenticators with the new user
        self._update_users_authenticators(authenticators, authenticator_uid, associated_authenticators, new_user)

        return new_user

    def get_last_login_from(self, obj):
        """
        Get the last_login_from field for the user.

        Returns:
            dict or None: Dictionary with authenticator details if user has logged in,
                         None if user has never logged in
        """
        if obj.last_login_from:
            return {'id': obj.last_login_from.id, 'name': obj.last_login_from.name, 'type': obj.last_login_from.type}
        return None

    def to_representation(self, obj):
        ret = super(UserSerializer, self).to_representation(obj)
        if password_is_usable(ret['password']):
            # If its an internal account lets assume there is a password and return a masked value to the user
            ret['password'] = ENCRYPTED_STRING
        else:
            # User does not have a local password, or password is unusable/ disabled
            ret['password'] = PASSWORD_DISABLED

        ret['managed'] = obj.managed

        # Get the users associated authenticator users
        authentications = AuthenticatorUser.objects.filter(user=obj)

        # Add last login results but only for yourself unless you are a superuser or auditor
        request = self.context.get('request', None)
        if request and request.user and (request.user.is_superuser or request.user.is_platform_auditor or request.user.username == obj.username):
            ret['last_login_results'] = {}
            for authentication in authentications:
                ret['last_login_results'][authentication.provider.id] = {
                    'access_allowed': authentication.access_allowed,
                    'last_login_map_results': authentication.last_login_map_results,
                    'last_login_attempt': authentication.extra_data.get('auth_time', 'Unknown'),
                }

        # Show which authenticators the user is related to for the admin/auditor
        if request and request.user and (request.user.is_superuser or request.user.is_platform_auditor or request.user.username == obj.username):
            ret['authenticators'] = obj.get_authenticator_ids()
            ret['authenticator_uid'] = ', '.join(obj.get_authenticator_uids())
            ret['associated_authenticators'] = obj.get_associated_authenticators()

        # Include deprecation warnings if any were generated during validation
        if hasattr(self, '_deprecation_warnings') and self._deprecation_warnings:
            ret['warnings'] = [w['message'] for w in self._deprecation_warnings]

        return ret

    def _get_related(self, obj) -> dict[str, str]:
        ret = super()._get_related(obj)
        ret['authenticators'] = get_relative_url('user-authenticators-list', kwargs={'pk': obj.pk})

        return ret
