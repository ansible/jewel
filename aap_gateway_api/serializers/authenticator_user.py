from ansible_base.authentication.models import Authenticator, AuthenticatorUser
from ansible_base.lib.serializers.common import AbstractCommonModelSerializer
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from aap_gateway_api.models import User


class AuthenticatorUserSerializer(AbstractCommonModelSerializer):
    class Meta:
        model = AuthenticatorUser
        fields = AbstractCommonModelSerializer.Meta.fields + [
            'provider',
            'user',
            'claims',
            'last_login_map_results',
            'access_allowed',
            'uid',
            'created',
            'modified',
        ]


class AuthenticatorUserMoveSerializer(serializers.Serializer):
    new_authenticator = serializers.PrimaryKeyRelatedField(
        queryset=Authenticator.objects.all(),
        help_text=_("The ID of the authenticator to which the user will be moved."),
    )
    keep_memberships = serializers.BooleanField(
        help_text=_("If false, remove the user's existing memberships and let the authenticator map for the new authenticator manage it instead."),
    )
    merge_with_user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        required=False,
        allow_null=True,
        help_text=_("An optional user to merge this account with."),
    )
    new_uid = serializers.CharField(
        required=False,
        allow_null=True,
        help_text=_(
            "Provide a new UID for the user. This value is used to link the users login with the local "
            "AAP account.  It must match the user identifier from the new authentication provider."
        ),
    )
    merge_accounts_with_same_uid = serializers.BooleanField(
        help_text=_("If true, automatically merge accounts with the same uid. Mutually exclusive with merge_with_user."),
    )
    remove_other_authenticators = serializers.BooleanField(
        help_text=_("If true, delete any other authenticator_user entries the user has from old_authenticator."),
    )

    def validate(self, data):
        if data.get("merge_with_user") and data.get("merge_accounts_with_same_uid"):
            raise serializers.ValidationError(_("merge_with_user and merge_accounts_with_same_uid are mutually exclusive"))

        return data
