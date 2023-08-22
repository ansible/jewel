from aap_gateway_api.models import User
from aap_gateway_api.serializers import CommonModelSerializer


class UserSerializer(CommonModelSerializer):
    reverse_url_name = 'user-detail'

    class Meta(CommonModelSerializer.Meta):
        model = User
        fields = CommonModelSerializer.Meta.fields + (
            'username',
            'email',
            'first_name',
            'last_name',
            'password',
            'is_superuser',
        )

    def to_representation(self, obj):
        ret = super(UserSerializer, self).to_representation(obj)
        # TODO: Defined users as "external" if they logged in from a source
        # if self.get_external_account(obj):
        #    # If this is an external account it shouldn't have a password field
        #    ret.pop('password', None)
        # else:
        if True:
            # If its an internal account lets assume there is a password and return $encrypted$ to the user
            ret['password'] = '$encrypted$'
        return ret
