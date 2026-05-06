from ansible_base.authentication.models import AuthenticatorUser
from django.contrib.auth.models import UserManager
from django.db.models import Prefetch


def with_auth_prefetch(queryset):
    """Apply standard select_related/prefetch_related for user serialization."""
    return queryset.select_related("resource", "last_login_from").prefetch_related(
        Prefetch("authenticator_users", queryset=AuthenticatorUser.objects.select_related("provider"))
    )


class UserUnmanagedManager(UserManager):
    def get_queryset(self):
        return super().get_queryset().filter(managed=False)

    def with_auth_prefetch(self):
        return with_auth_prefetch(self.get_queryset())
