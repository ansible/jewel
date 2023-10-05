from django.contrib.auth.hashers import is_password_usable

from aap_gateway_api.models import User
from aap_gateway_api.serializers.common import CommonModelSerializer
from aap_gateway_api.utils import ENCRYPTED_STRING


class UserSerializer(CommonModelSerializer):
    reverse_url_name = 'user-detail'

    class Meta(CommonModelSerializer.Meta):
        model = User
        fields = CommonModelSerializer.Meta.fields + [
            'username',
            'email',
            'first_name',
            'last_name',
            'password',
            'is_superuser',
            'is_system_auditor',
            'last_login_map_results',
        ]

    def get_fields(self, *args, **kwargs):
        fields = super().get_fields(*args, **kwargs)
        request = self.context.get('request', None)
        # Do not require the password field unless we are creating a new user
        if request and getattr(request, 'method', None) != "POST":
            fields['password'].required = False
        return fields

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
        return ret
