import logging

from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.lib.serializers.common import CommonModelSerializer
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from crum import get_current_user
from django.contrib.auth.hashers import is_password_usable
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.serializers import ValidationError

from aap_gateway_api.models import Organization, User
from aap_gateway_api.utils import get_preference_value

logger = logging.getLogger('aap.gateway.serializer.user')


class UserSerializer(CommonModelSerializer):
    reverse_url_name = 'user-detail'
    # This needs to be explicitly so it's not required
    organizations = serializers.PrimaryKeyRelatedField(many=True, queryset=Organization.objects.all(), required=False)

    class Meta(CommonModelSerializer.Meta):
        model = User
        fields = CommonModelSerializer.Meta.fields + [
            'username',
            'email',
            'first_name',
            'last_name',
            'last_login',
            'password',
            'is_superuser',
            'is_system_auditor',
            'organizations',
        ]
        read_only_fields = ["last_login"]

    def get_fields(self, *args, **kwargs):
        fields = super().get_fields(*args, **kwargs)
        request = self.context.get('request', None)
        # Do not require the password field unless we are creating a new user
        if request and getattr(request, 'method', None) != "POST":
            fields['password'].required = False
        return fields

    def validate(self, data):
        # Validate the password
        if data.get('password') and data.get('password') != ENCRYPTED_STRING:
            password_min_length = get_preference_value('local_login', 'password_min_length')
            password_min_digits = get_preference_value('local_login', 'password_min_digits')
            password_min_upper = get_preference_value('local_login', 'password_min_upper')
            password_min_special = get_preference_value('local_login', 'password_min_special')

            errors = []
            if password_min_length > 0 and len(data['password']) < password_min_length:
                errors.append(_('Password must be at least {} characters long.'.format(password_min_length)))
            if password_min_digits > 0 and sum(c.isdigit() for c in data['password']) < password_min_digits:
                errors.append(_('Password must contain at least {} digits.'.format(password_min_digits)))
            if password_min_upper > 0 and sum(c.isupper() for c in data['password']) < password_min_upper:
                errors.append(_('Password must contain at least {} uppercase characters.'.format(password_min_upper)))
            if password_min_special > 0 and sum(not c.isalnum() for c in data['password']) < password_min_special:
                errors.append(_('Password must contain at least {} special characters.'.format(password_min_special)))

            if errors:
                request = self.context.get('request', None)
                allow_admins_to_set_insecure = get_preference_value('local_login', 'allow_admins_to_set_insecure')
                if request and request.user and request.user.is_superuser and allow_admins_to_set_insecure:
                    user = get_current_user()
                    username = data.get('username', None)
                    if username is None:
                        instance = getattr(self, 'instance', None)
                        if instance is None:
                            raise ValidationError("Either username needs to be present or we need an active instance")
                        username = instance.username
                    logger.warning(f"User {user.username} was allowed to save an insecure password for user {username}")
                else:
                    raise ValidationError({'password': errors})

        return data

    def update(self, instance, validated_data):
        # We don't want the $encrypted$ password going back to the model
        new_password = validated_data.get('password', None)
        if new_password and new_password == ENCRYPTED_STRING:
            validated_data.pop('password', None)

        return super().update(instance, validated_data)

    def to_representation(self, obj):
        ret = super(UserSerializer, self).to_representation(obj)
        if is_password_usable(ret['password']):
            # If its an internal account lets assume there is a password and return a masked value to the user
            ret['password'] = ENCRYPTED_STRING
        else:
            # User does not have a local password so pop this field
            ret.pop('password', None)

        # Add last login results but only for yourself unless you are a superuser or auditor
        request = self.context.get('request', None)
        if request and request.user and (request.user.is_superuser or request.user.is_system_auditor or request.user.username == obj.username):
            ret['last_login_results'] = {}
            authentications = AuthenticatorUser.objects.filter(user=obj)
            for authentication in authentications:
                ret['last_login_results'][authentication.provider.id] = {
                    'access_allowed': authentication.access_allowed,
                    'last_login_map_results': authentication.last_login_map_results,
                    'last_login_attempt': authentication.extra_data.get('auth_time', 'Unknown'),
                }

        return ret
