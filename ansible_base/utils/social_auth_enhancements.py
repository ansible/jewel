from django.db import models
from django.db.utils import IntegrityError
from social_core.utils import setting_name
from social_django.models import Association, Code, Nonce, Partial
from social_django.storage import BaseDjangoStorage
from social_django.strategy import DjangoStrategy

from ansible_base.authentication.authenticators import get_authenticator_class, get_authenticator_plugins
from ansible_base.models import Authenticator, AuthenticatorUser


class AuthenticatorStorage(BaseDjangoStorage):
    user = AuthenticatorUser
    nonce = Nonce
    association = Association
    code = Code
    partial = Partial

    @classmethod
    def is_integrity_error(cls, exception):
        return exception.__class__ is IntegrityError


class AuthenticatorStrategy(DjangoStrategy):
    # override setting to pass the backend to get_setting
    def setting(self, name, default=None, backend=None):
        names = [setting_name(name), name]
        if backend:
            names.insert(0, setting_name(backend.name, name))
        for name in names:
            try:
                return self.get_setting(name, backend)
            except (AttributeError, KeyError):
                pass
        return default

    # load the authenticator setting from the database object.
    def get_setting(self, name, backend):
        # try to load the value from the db.
        value = backend.database_instance.configuration.get(name)

        # fall  back to settings module
        if value is None:
            return super().get_setting(name)
        return value

    def get_backends(self):
        """Return configured backends"""
        return get_authenticator_plugins()

    def get_backend_class(self, name):
        """Return a configured backend class"""
        return get_authenticator_class(name)

    def get_backend(self, name, redirect_uri=None, *args, **kwargs):
        """Add the database instance arg into the social auth backend."""

        db_instance = Authenticator.objects.get(pk=name)
        Backend = self.get_backend_class(db_instance.type)

        kwargs["database_instance"] = db_instance
        kwargs["redirect_uri"] = redirect_uri
        args = (self,) + args

        return Backend(
            *args,
            **kwargs,
        )

    def session_set(self, name, value):
        # Social auth tries to set auth_user.provider as a value in the session. Since
        # we've set provider to be a foreign key to the Authenticator model, this can
        # receive an Authenticator object, which isn't json serializeable and causes the
        # session to break.
        if isinstance(value, models.Model):
            value = str(value)
        return super().session_set(name, value)


def create_user_claims_pipeline(*args, backend, **kwargs):
    from ansible_base.authentication.authenticator_lib import update_user_claims

    update_user_claims(kwargs["user"], backend.database_instance, backend.get_user_groups())
