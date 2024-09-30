from django.utils.translation import gettext as _
from rest_framework import serializers

from aap_gateway_api.models import MigratedUserMetadata, User

LOCAL_AUTHENTICATOR = "ansible_base.authentication.authenticator_plugins.local"
LEGACY_PASSWORD = "aap_gateway_api.authentication.authenticator_plugins.legacy_password"


class LinkedAccountSerializer(serializers.ModelSerializer):
    service_type = serializers.CharField(source="service.service_type")
    gateway_username = serializers.CharField(source="user.username")
    ansible_id = serializers.CharField(source="user.resource.ansible_id")

    class Meta:
        model = MigratedUserMetadata
        fields = (
            "service",
            "service_type",
            "original_username",
            "user",
            "gateway_username",
            "ansible_id",
            "backend_classification",
        )


def user_has_external_password(user: User):
    # Note: backend_classification__in=[None] doesn't seem to work
    return user.original_accounts.exclude(backend_classification="local").exclude(backend_classification=None).exists()


def can_user_set_password(user: User):
    # If the user has any authenticator other than legacy_password or local, don't allow setting a password

    if user_has_external_password(user):
        return False

    return (
        not user.authenticator_users.exclude(
            provider__type=LOCAL_AUTHENTICATOR,
        )
        .exclude(
            provider__type=LEGACY_PASSWORD,
        )
        .exists()
    )


def user_needs_aap_password(user: User):
    if user.authenticator_users.filter(provider__type__endswith="local").exists() and user.has_usable_password():
        return False

    return can_user_set_password(user)


def can_user_change_username(user: User):
    return not user_has_external_password(user)


class LegacyAuthSerializer(serializers.ModelSerializer):
    linked_accounts = LinkedAccountSerializer(many=True, source="original_accounts")

    needs_rename = serializers.SerializerMethodField()
    is_authenticated = serializers.SerializerMethodField()
    needs_aap_password = serializers.SerializerMethodField()
    allow_rename = serializers.SerializerMethodField()
    allow_aap_password = serializers.SerializerMethodField()
    is_sso_account = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "is_authenticated",
            "needs_rename",
            "is_migrated",
            "linked_accounts",
            "needs_aap_password",
            "allow_rename",
            "allow_aap_password",
            "is_sso_account",
        )

    def get_needs_rename(self, user):
        return self.context["needs_rename"]

    def get_is_authenticated(self, user):
        authed_user = self.context["request"].user
        return authed_user.pk == user.pk

    def get_allow_rename(self, obj):
        return can_user_change_username(obj)

    def get_needs_aap_password(self, obj):
        return user_needs_aap_password(obj)

    def get_allow_aap_password(self, obj):
        return can_user_set_password(obj)

    def get_is_sso_account(self, obj):
        return obj.authenticator_users.filter(provider__migrated_metadata__type="legacy_sso").exists()


class FinalizeSerializer(serializers.Serializer):
    new_username = serializers.CharField(required=False)
    aap_password = serializers.CharField(required=False, style={'input_type': 'password'})

    def validate(self, data):
        user = self.context.get("user")

        username = data.get("new_username", None)
        password = data.get("aap_password", None)

        if self.context.get("needs_rename", True):
            if can_user_change_username(user):
                if not username:
                    raise serializers.ValidationError({"new_username": _("Please pick a new username.")})

        if user_needs_aap_password(user) and not password:
            raise serializers.ValidationError({"aap_password": _("You must pick an AAP password before you can finish logging in.")})

        if password and not can_user_set_password(user):
            raise serializers.ValidationError({"aap_password": _("This account is set up to use external authentication and cannot set an AAP password.")})

        if username and not can_user_change_username(user):
            raise serializers.ValidationError(
                {"new_username": _("This account is using an external authentication provider that does not allow users to change their username.")}
            )

        return data


class UsernamePasswordSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(style={'input_type': 'password'})
