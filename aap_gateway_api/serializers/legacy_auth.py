from django.utils.translation import gettext as _
from rest_framework import serializers

from aap_gateway_api.models import MigratedUserMetadata, ServiceCluster, User


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
        )


class LegacyAuthSerializer(serializers.ModelSerializer):
    linked_accounts = LinkedAccountSerializer(many=True, source="original_accounts")

    needs_rename = serializers.SerializerMethodField()
    is_authenticated = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "is_authenticated",
            "needs_rename",
            "is_migrated",
            "linked_accounts",
        )

    def get_needs_rename(self, user):
        return self.context["needs_rename"]

    def get_is_authenticated(self, user):
        authed_user = self.context["request"].user
        return authed_user.pk == user.pk


class RenameAccountSerializer(serializers.Serializer):
    new_username = serializers.CharField(required=False)

    def validate(self, data):
        username = data.get("new_username", None)
        if self.context.get("needs_rename", True):
            if not username:
                raise serializers.ValidationError({"new_username": _("Please pick a new username.")})
        return data


class UsernamePasswordSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()
    service_type = serializers.ChoiceField(choices=ServiceCluster.ServiceType.choices)
