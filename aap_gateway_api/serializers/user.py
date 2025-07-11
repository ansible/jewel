import logging

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugin
from ansible_base.authentication.models import Authenticator, AuthenticatorUser
from ansible_base.authentication.utils.authentication import determine_username_from_uid
from ansible_base.authentication.utils.user import can_user_change_password
from ansible_base.lib.serializers.common import CommonUserSerializer
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from ansible_base.lib.utils.response import get_relative_url
from crum import get_current_user
from django.contrib.auth import update_session_auth_hash
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import EmailValidator
from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail
from rest_framework.fields import empty
from rest_framework.serializers import ValidationError

from aap_gateway_api.models import User
from aap_gateway_api.models.user import password_is_usable
from aap_gateway_api.utils import get_preference_value

logger = logging.getLogger('aap.gateway.serializer.user')

PASSWORD_DISABLED = 'Password Disabled'  # signal unusable passwords


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
    )

    authenticator_uid = serializers.CharField(write_only=True, required=False, allow_blank=True)
    associated_authenticators = serializers.JSONField(write_only=True, required=False)
    is_platform_auditor = serializers.BooleanField(read_only=True)

    def __init__(self, instance=None, data=empty, **kwargs):
        super().__init__(instance, data, **kwargs)

        self.fields['authenticators'].choices = list(Authenticator.objects.all().values_list('id', 'name').order_by('name'))

    class Meta(CommonUserSerializer.Meta):
        model = User
        fields = CommonUserSerializer.Meta.fields + [
            'username',
            'email',
            'first_name',
            'last_name',
            'last_login',
            'password',
            'is_superuser',
            'is_platform_auditor',
            'authenticators',
            'authenticator_uid',
            'associated_authenticators',
            'managed',
        ]
        read_only_fields = ["last_login", "is_platform_auditor"]

    def is_superuser_making_request(self) -> bool:
        request = self.context.get('request', None)
        if request and hasattr(request, 'user') and request.user.is_superuser:
            return True
        return False

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

    def validate_authenticator_uid(self, value: str) -> str:
        """
        Ensure that when a user has multiple authenticators, their authenticator_uid field
        cannot be changed (to avoid ambiguity).
        Single-authenticator users can freely update their authenticator_uid.
        """
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
            raise ValidationError(
                _(
                    "UID changes are not supported for users with multiple authenticators to "
                    "prevent ambiguous updates. Use specific authenticator endpoints for changes. "
                    "If you are deleting the authenticator leave this field as is."
                )
            )

        return value

    def _is_authenticator_uid_unchanged(self, value: str, current_uids: list[str]) -> bool:
        incoming_values = {uid.strip() for uid in value.split(',') if uid.strip()}
        return incoming_values == set(current_uids)

    def validate_authenticators(self, value):
        """
        1. Enforce the single authenticator rule, with an exception for migrated users.
        2. Skip validation if the authenticators are not changing or are being removed.
        3. Authenticator ID validation is implicitly handled by DRF's choice field validation.

        Note: The restriction of authenticator modifications to superusers is enforced at the view level.
        """
        user_instance = self.instance  # This will be None for creation

        # Get the user's current authenticators (if there is a user)
        current_authenticators = user_instance.get_authenticator_ids() if user_instance else []

        # If the authenticators are not changing, it's fine
        if value is None or (set(value) == set(current_authenticators)):
            return value

        # Handle specific case for removing a provider from a migrated user with multiple authenticators
        if user_instance and value != current_authenticators:
            if self._is_only_removing_authenticators(value, current_authenticators):
                return value

        # Enforce the rule: a user cannot be tied to multiple authenticators
        if len(value) > 1:
            raise ValidationError(ErrorDetail(_("You can only tie a user to a single authenticator"), code='multiple_authenticators'))

        return value

    def validate_associated_authenticators(self, value):
        """
        Validate the associated_authenticators field by coordinating helper validations.
        """
        if not value:
            return value

        if not self.is_superuser_making_request():
            raise serializers.ValidationError(_("Only superusers can manage associated_authenticators using this field."))

        if not isinstance(value, dict):
            raise serializers.ValidationError(_("This field must be a JSON object (dictionary)."))

        self._validate_authenticator_keys_exist(value.keys())
        self._validate_authenticator_details_format(value)

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

    def validate(self, data):
        """
        Perform cross-field validation for authenticators and authenticator_uid.

        This method:
        1. Handles partial updates for authenticator_uid.
        2. Validates authenticator and UID combinations:
           - Ensures UID is present when adding/modifying authenticators.
           - Checks for UID conflicts across authenticators.
           - Validates new authenticators for conflicts.
        3. Ensures authenticator_uid is empty when removing all authenticators.

        Raises ValidationError if any validation fails.
        """
        authenticators = data.get('authenticators')
        authenticator_uid = data.get('authenticator_uid')

        user_instance = self.instance  # This will be None for creation
        current_authenticators = user_instance.get_authenticator_ids() if user_instance else []

        self._handle_partial_update(data, user_instance)

        errors = {}
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
            self._validate_uid_presence(authenticator_uid, authenticators, errors)
            self._validate_uid_conflicts(authenticators, authenticator_uid, user_instance, errors)
            self._validate_new_authenticators(authenticators, authenticator_uid, user_instance, current_authenticators, errors)

    def _is_only_removing_authenticators(self, authenticators, current_authenticators):
        return set(authenticators) < set(current_authenticators)

    def _validate_uid_presence(self, authenticator_uid, authenticators, errors):
        # Ensure authenticator_uid is not empty when setting authenticators
        if not authenticator_uid and authenticators:
            errors.setdefault('authenticator_uid', []).append(ErrorDetail(_("Authenticator UID cannot be empty when setting authenticators."), code='required'))

    def _validate_uid_conflicts(self, authenticators, authenticator_uid, user_instance, errors):
        for authenticator_id in authenticators:
            authenticator = Authenticator.objects.get(id=authenticator_id)
            # Check for UID conflicts using Q objects for efficiency
            if AuthenticatorUser.objects.filter(Q(uid=authenticator_uid) & Q(provider=authenticator)).exclude(user=user_instance).exists():
                errors.setdefault('authenticator_uid', []).append(
                    ErrorDetail(_("UID is already in use for authenticator: {}").format(authenticator.name), code='unique')
                )

    def _validate_new_authenticators(self, authenticators, authenticator_uid, user_instance, current_authenticators, errors):
        # Handle the specific case for new authenticators being added
        new_authenticators = set(authenticators) - set(current_authenticators)
        for authenticator_id in new_authenticators:
            self._check_conflicting_user(authenticator_id, authenticator_uid, user_instance, errors)

    def _check_conflicting_user(self, authenticator_id, authenticator_uid, user_instance, errors):
        authenticator = Authenticator.objects.get(id=authenticator_id)

        # If an authenticator_uid is provided, check for UID conflicts
        if authenticator_uid:
            conflicting_user = AuthenticatorUser.objects.filter(uid=authenticator_uid, provider=authenticator).exclude(user=user_instance).first()
            # Since we found a conflicting user we can't let this user be added to this authenticator
            if conflicting_user:
                errors.setdefault('authenticator_uid', []).append(
                    ErrorDetail(
                        _("UID '{uid}' is already in use for authenticator: {auth}").format(auth=authenticator.name, uid=authenticator_uid),
                        code='uid_conflict',
                    )
                )
                errors.setdefault('authenticators', []).append(
                    ErrorDetail(
                        _("Cannot set authenticator '{auth}': UID '{uid}' is already in use by user '{user}'").format(
                            auth=authenticator.name, uid=authenticator_uid, user=conflicting_user.user.username
                        ),
                        code='uid_conflict',
                    )
                )

    def _validate_empty_authenticators(self, authenticators, authenticator_uid, errors):
        if authenticators is not None and len(authenticators) == 0 and authenticator_uid:
            errors.setdefault('authenticator_uid', []).append(
                ErrorDetail(_("Authenticator UID should be empty when removing all authenticators."), code='invalid')
            )

    def validate_username(self, value):
        """
        1. Check if the username is being changed.
        2. For each authenticator associated with the user, determine the expected username
           based on the authenticator's rules and the new username value.
        3. Raise a ValidationError if the new username doesn't match the expected username
           for any associated authenticator.

        This validation ensures that the new username complies with the rules of all
        associated authenticators, including potential modifications (e.g., adding a hash)
        to maintain uniqueness across the system.
        """
        user_instance = self.instance  # This will be None for creation
        old_username = user_instance.username if user_instance else None

        errors = []

        if old_username and value != old_username:
            for authenticator_user in user_instance.authenticator_users.all():
                expected_username = determine_username_from_uid(value, authenticator_user.provider)

                if expected_username != value:
                    errors.append(
                        ErrorDetail(
                            _(
                                "New username '%(value)s' does not comply with the rules for authenticator '%(auth)s'. "
                                "The expected username would be '%(expected)s'. "
                                "This may be due to conflicts with existing usernames or authenticator-specific rules."
                            )
                            % {'value': value, 'expected': expected_username, 'auth': authenticator_user.provider.name},
                            code='invalid',
                        )
                    )

        if errors:
            raise ValidationError({'username': errors})

        return value

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
            authenticator = Authenticator.objects.get(id=add_authenticator_id)
            logger.info(f"Adding authenticator {authenticator.name} with UID {authenticator_uid} for user {user_instance.username}")

            auth_type = get_authenticator_plugin(authenticator.type).type
            username = user_instance.username

            if auth_type == 'local':
                # For local authenticators, UID must match the username
                new_uid = username
                if username != authenticator_uid:
                    logger.info(
                        f"Creating new user {username} with authenticator_uid {username} for the local authenticator {authenticator.name}; "
                        "uid must match username for local authenticator users"
                    )
            else:
                new_uid = authenticator_uid

            AuthenticatorUser.objects.create(uid=new_uid, user=user_instance, provider=authenticator, email=email)

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
            return  # No update needed if UID is unchanged

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
                f"Updating UID to {new_uid} for user {new_username} "
                f"(old username: {authenticator_user.user.username}) on {authenticator_user.provider.name}"
            )

            authenticator_user.uid = new_uid
            authenticator_user.save(update_fields=['uid'])

        logger.info(f"Updated authenticator UID to {authenticator_uid}")

    def _update_users_authenticators(self, authenticators, authenticator_uid, associated_authenticators, user_instance):
        """
        Update user's authenticators:
        1. Remove old authenticators
        2. Add new authenticators
        3. Update UIDs if changed
        Log all actions performed.
        """
        logger.info(f"Updating authenticators for user {user_instance.username}")

        existing_authenticators = user_instance.get_authenticator_ids()

        if 'associated_authenticators' in self.initial_data:
            if existing_authenticators:
                self._remove_authenticators(existing_authenticators, user_instance)

            for auth_id_str, data in associated_authenticators.items():
                specific_uid = data.get('uid')
                email = data.get('email')
                if specific_uid is not None:
                    self._add_authenticators([int(auth_id_str)], specific_uid, user_instance, email)
                    self._update_authenticator_uids(specific_uid, user_instance)

        elif authenticators is not None:
            authenticators_to_remove = set(existing_authenticators) - set(authenticators)
            authenticators_to_add = set(authenticators) - set(existing_authenticators)

            self._remove_authenticators(authenticators_to_remove, user_instance)
            self._add_authenticators(authenticators_to_add, authenticator_uid, user_instance)
            self._update_authenticator_uids(authenticator_uid, user_instance)

        logger.info(f"Successfully updated authenticators for user {user_instance.username}")

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
            # We're in @transaction.atomic, so we don't risk uid getting out of sync here.
            instance.update_local_authenticator_uid_from_username()

        # Remove the authenticators field since thats not a real field on the User model
        authenticators = validated_data.pop('authenticators', None)
        authenticator_uid = validated_data.pop('authenticator_uid', None)
        associated_authenticators = validated_data.pop('associated_authenticators', None)

        # Update the User model with validated data
        instance = super().update(instance, validated_data)
        # Handle authenticator changes
        self._update_users_authenticators(authenticators, authenticator_uid, associated_authenticators, instance)

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

    def to_representation(self, obj):
        ret = super(UserSerializer, self).to_representation(obj)
        if password_is_usable(ret['password']):
            # If its an internal account lets assume there is a password and return a masked value to the user
            ret['password'] = ENCRYPTED_STRING
        else:
            # User does not have a local password, or password is unusable/ disabled
            ret['password'] = PASSWORD_DISABLED

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

        return ret

    def _get_related(self, obj) -> dict[str, str]:
        ret = super()._get_related(obj)
        ret['authenticators'] = get_relative_url('user-authenticators-list', kwargs={'pk': obj.pk})

        return ret
