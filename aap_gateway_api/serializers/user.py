import logging

from ansible_base.authentication.models import Authenticator, AuthenticatorUser
from ansible_base.authentication.utils.user import can_user_change_password
from ansible_base.lib.serializers.common import CommonUserSerializer
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from crum import get_current_user
from django.contrib.auth.hashers import is_password_usable
from django.db.utils import IntegrityError
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.fields import empty
from rest_framework.serializers import ValidationError

from aap_gateway_api.models import Organization, User
from aap_gateway_api.utils import get_preference_value

logger = logging.getLogger('aap.gateway.serializer.user')


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

    def __init__(self, instance=None, data=empty, **kwargs):
        super().__init__(instance, data, **kwargs)

        self.fields['authenticators'].choices = list(Authenticator.objects.all().values_list('id', 'name').order_by('name'))
        request = self.context.get('request')
        if request:
            self.fields['organizations'].queryset = Organization.access_qs(request.user)
            self.fields['organizations'].child_relation.queryset = Organization.access_qs(request.user)
            self.fields['organizations'].required = False

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
            'is_system_auditor',
            'organizations',
            'authenticators',
            'authenticator_uid',
        ]
        read_only_fields = ["last_login"]

    def is_superuser_making_request(self) -> bool:
        request = self.context.get('request', None)
        if request and hasattr(request, 'user') and request.user.is_superuser:
            return True
        return False

    def validate_password(self, value: str) -> str:
        errors = []
        # Validate the password
        if value and value != ENCRYPTED_STRING:
            user_instance = getattr(self, 'instance', None)
            if user_instance is not None:
                if not can_user_change_password(user_instance):
                    raise ValidationError(_('Password can not be set for this user'))

            password_min_length = get_preference_value('local_login', 'password_min_length')
            password_min_digits = get_preference_value('local_login', 'password_min_digits')
            password_min_upper = get_preference_value('local_login', 'password_min_upper')
            password_min_special = get_preference_value('local_login', 'password_min_special')

            if password_min_length > 0 and len(value) < password_min_length:
                errors.append(_('Password must be at least {} characters long.'.format(password_min_length)))
            if password_min_digits > 0 and sum(c.isdigit() for c in value) < password_min_digits:
                errors.append(_('Password must contain at least {} digits.'.format(password_min_digits)))
            if password_min_upper > 0 and sum(c.isupper() for c in value) < password_min_upper:
                errors.append(_('Password must contain at least {} uppercase characters.'.format(password_min_upper)))
            if password_min_special > 0 and sum(not c.isalnum() for c in value) < password_min_special:
                errors.append(_('Password must contain at least {} special characters.'.format(password_min_special)))

            if errors:
                allow_admins_to_set_insecure = get_preference_value('local_login', 'allow_admins_to_set_insecure')
                if self.is_superuser_making_request() and allow_admins_to_set_insecure:
                    user = get_current_user()
                    username = self.initial_data.get('username', None)
                    if username is None:
                        if user_instance is None:
                            raise ValidationError(_("Either username needs to be present or we need an active instance"))
                        username = user_instance.username
                    logger.warning(f"User {user.username} was allowed to save an insecure password for user {username}")
                else:
                    raise ValidationError(errors)

        return value

    def validate_authenticator_uid(self, value: str) -> str:
        user_instance = getattr(self, 'instance', None)

        current_uid = []
        if user_instance:
            current_uid = user_instance.get_authenticator_uids()

        # If nothing is changing its fine
        if value == ', '.join(current_uid):
            return value

        if not self.is_superuser_making_request():
            raise ValidationError(_("Only a superuser is allowed to change this field"))

        # Its not possible to change the UID when working with multiple authenticators
        # (because we don't know which is which)
        # if we made it here we already know the value is changing
        if user_instance and len(user_instance.get_authenticator_uids()) > 1:
            raise ValidationError(
                _("You can not change this if the user is tied to multiple authenticators. If you are deleting the authenticator leave this field as is.")
            )

        return value

    def validate_authenticators(self, value: str) -> str:
        user_instance = getattr(self, 'instance', None)

        # Get the users current authenticators (if there is a user)
        current_authenticators = []
        if user_instance:
            current_authenticators = user_instance.get_authenticator_ids()

        # If nothing is changing its fine
        if value is None or (set(value) == set(current_authenticators)):
            return value

        # Only admin is allowed to change the authenticators/authenticator_uid
        if not self.is_superuser_making_request():
            raise ValidationError(_("Only a superuser is allowed to change this field"))

        if user_instance and value != current_authenticators:
            # We have one special use case were maybe we are removing a provider from a migrated user who had multiple authenticators
            if set(value).issubset(set(current_authenticators)):
                return value

            # We don't want a user tied to multiple authenticators normally
            if len(value) > 1:
                raise ValidationError(_("You can only tie a user to a single authenticator"))
        return value

    def update_users_authenticators(self, authenticators, authenticator_uid, user_object):
        existing_authenticators = user_object.get_authenticator_ids()
        existing_authenticator_uid = user_object.get_authenticator_uids()

        if authenticators is not None and set(authenticators) != set(existing_authenticators):
            logger.info(f"Changing authenticator instances for {user_object.username} from {existing_authenticators} to {list(authenticators)}")

            # remove any authenticators which are no longer being used
            for remove_authenticator_id in set(existing_authenticators).difference(set(authenticators)):
                logger.debug(f"Deleting authenticator {remove_authenticator_id} from {user_object.username}")
                user_object.authenticator_users.get(provider__id=remove_authenticator_id).delete()

            # Add the new authenticators
            for add_authenticator_id in set(authenticators).difference(set(existing_authenticators)):
                logger.debug(f"Adding authenticator {add_authenticator_id} to {user_object.username}")
                authenticator = Authenticator.objects.get(id=add_authenticator_id)
                try:
                    AuthenticatorUser.objects.create(uid=authenticator_uid, user=user_object, provider=authenticator)
                except IntegrityError:
                    logger.error(
                        f"Unable to add {user_object.username} to authenticator {authenticator.name}"
                        f" because uid {authenticator_uid} is already in use for that authenticator"
                    )
                    raise ValidationError({"authenticators": _("Can not be set because UID is already in use")})
        elif authenticator_uid is not None and authenticator_uid != existing_authenticator_uid:
            # We just requested to change the uid
            for authenticator_user in user_object.authenticator_users.all():
                logger.debug(f"Setting uid to {authenticator_uid} for {user_object.username} on {authenticator_user.provider.name}")
                authenticator_user.uid = authenticator_uid
                try:
                    authenticator_user.save(update_fields=['uid'])
                except Exception:
                    logger.error(
                        f"Unable to update {user_object.username}'s UID to {authenticator_uid}"
                        f" because is already in use by authenticator {authenticator_user.provider.name}"
                    )
                    raise ValidationError({"authenticator_uid": _("UID is already in use for given authenticator")})

    def update(self, instance, validated_data):
        # We don't want the $encrypted$ password going back to the model
        new_password = validated_data.get('password', None)
        if new_password and new_password == ENCRYPTED_STRING:
            validated_data.pop('password', None)

        # Remove the authenticators field since thats not a real field on the User model
        authenticators = validated_data.pop('authenticators', None)
        authenticator_uid = validated_data.pop('authenticator_uid', None)

        # Update the User model
        return_value = super().update(instance, validated_data)

        self.update_users_authenticators(authenticators, authenticator_uid, instance)

        return return_value

    def create(self, validated_data):
        # Remove the authenticators field since thats not a real field on the User model
        authenticators = validated_data.pop('authenticators', None)
        authenticator_uid = validated_data.pop('authenticator_uid', None)

        if authenticators and not authenticator_uid:
            raise ValidationError({'authenticator_uid': 'Must be set if authenticators are set'})

        # Create the User model
        new_user = super().create(validated_data)

        self.update_users_authenticators(authenticators, authenticator_uid, new_user)

        return new_user

    def to_representation(self, obj):
        ret = super(UserSerializer, self).to_representation(obj)
        if is_password_usable(ret['password']):
            # If its an internal account lets assume there is a password and return a masked value to the user
            ret['password'] = ENCRYPTED_STRING
        else:
            # User does not have a local password so pop this field
            ret.pop('password', None)

        # Get the users associated authenticator users
        authentications = AuthenticatorUser.objects.filter(user=obj)

        # Add last login results but only for yourself unless you are a superuser or auditor
        request = self.context.get('request', None)
        if request and request.user and (request.user.is_superuser or request.user.is_system_auditor or request.user.username == obj.username):
            ret['last_login_results'] = {}
            for authentication in authentications:
                ret['last_login_results'][authentication.provider.id] = {
                    'access_allowed': authentication.access_allowed,
                    'last_login_map_results': authentication.last_login_map_results,
                    'last_login_attempt': authentication.extra_data.get('auth_time', 'Unknown'),
                }

        # Show which authenticators the user is related to for the admin/auditor
        if request and request.user and (request.user.is_superuser or request.user.is_system_auditor or request.user.username == obj.username):
            ret['authenticators'] = obj.get_authenticator_ids()
            ret['authenticator_uid'] = ', '.join(obj.get_authenticator_uids())

        return ret

    def _get_related(self, obj) -> dict[str, str]:
        ret = super()._get_related(obj)
        ret['authenticators'] = reverse('user-authenticators-list', kwargs={'pk': obj.pk})
        ret['teams'] = reverse('user-teams-list', kwargs={'pk': obj.pk})
        ret['organizations'] = reverse('user-organizations-list', kwargs={'pk': obj.pk})
        return ret
