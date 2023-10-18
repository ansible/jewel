import logging
import time

from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.fields import empty
from rest_framework.serializers import ValidationError
from social_core.pipeline.user import get_username

from ansible_base.models import Authenticator, AuthenticatorUser
from ansible_base.utils.social_auth_enhancements import AuthenticatorStorage, AuthenticatorStrategy
from ansible_base.utils.validation import validate_url

from .common import create_claims

logger = logging.getLogger('ansible_base.authentication.authenticator_lib')


def get_local_username(user_details, authenticator):
    """
    Converts the username provided by the backend to one that doesn't conflict with users
    from other auth backends.
    """

    class FakeBackend:
        def setting(self, *args, **kwargs):
            return ["username", "email"]

    username = get_username(strategy=AuthenticatorStrategy(AuthenticatorStorage()), details=user_details, backend=FakeBackend())

    if username:
        return username["username"]
    else:
        return user_details["username"]


def get_or_create_authenticator_user(user_id, user_details, authenticator, extra_data):
    """
    Create the user object in the database along with it's associated AuthenticatorUser class.
    """

    extra = {**extra_data, "auth_time": int(time.time())}

    try:
        auth_user = AuthenticatorUser.objects.get(uid=user_id, provider=authenticator)
        auth_user.extra_data = extra
        auth_user.save()
        return (auth_user, False)
    except AuthenticatorUser.DoesNotExist:
        username = get_local_username(user_details, authenticator)

        # ensure the authenticator isn't trying to pass along a cheeky is_superuser in user_details
        allowed_keys = ["first_name", "last_name", "email"]
        details = {k: user_details.get(k, "") for k in allowed_keys if k}

        local_user, created = get_user_model().objects.get_or_create(username=username, defaults=details)

        return (AuthenticatorUser.objects.create(user=local_user, uid=user_id, extra_data=extra, provider=authenticator), True)


def update_user_claims(user, database_authenticator, groups):
    results = create_claims(database_authenticator, user.username, user.authenticator_user.extra, groups)

    needs_save = False
    for attribute, attr_value in results.items():
        if attr_value is None:
            continue
        logger.debug(f"{attribute}: {attr_value}")
        if getattr(user, attribute) != attr_value:
            logger.debug(f"Setting new attribute {attribute} for {user.username}")
            setattr(user, attribute, attr_value)
            needs_save = True

    if needs_save:
        user.save()

    if results['access_allowed'] is not True:
        logger.warning(f"User {user.username} failed an allow map and was denied access")
        return None
    return user


class URLField(serializers.CharField):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        def validator(value):
            return validate_url(value, schemes=["https", "http"], allow_plain_hostname=True)

        self.validators.append(validator)


class BaseAuthenticatorConfiguration(serializers.Serializer):
    documentation_url = None

    def get_configuration_schema(self):
        fields = self.get_fields()

        schema = []

        for f in fields:
            field = fields[f]
            default = None
            print(empty)
            if field.default is not empty:
                default = field.default

            schema.append({"name": f, "help_text": field.help_text, "required": not field.allow_null, "default": default, "type": field.__class__.__name__})
        return schema


class SocialAuthMixin:
    configuration_encrypted_fields = []
    logger = None

    def __init__(self, *args, **kwargs):
        # social auth expects the first arg to be a strategy instance. Since this has
        # to be instantiated outside of social auth, make sure that the strategy arg
        # is present.
        args = self.ensure_strategy_in_args(args)
        self.database_instance = kwargs.pop("database_instance", None)
        super().__init__(*args, **kwargs)
        self.set_logger(self.logger)

    @property
    def name(self):
        return str(self.database_instance.slug)

    def get_user_groups(self):
        """
        Receives the user object that .authenticate returns.
        """
        return []

    def ensure_strategy_in_args(self, args):
        if len(args) == 0:
            args = (AuthenticatorStrategy(storage=AuthenticatorStorage()),)

        return args


class AbstractAuthenticatorPlugin:
    """
    Base class for non social auth backends
    """

    configuration_class = BaseAuthenticatorConfiguration

    def __init__(self, database_instance=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.database_instance = database_instance

    def set_logger(self, logger) -> None:
        if not logger:
            self.logger = logging.getLogger('ansible_base.models.abstract_authenticator')
        else:
            self.logger = logger

    def validate_configuration(self, data: dict, instance: object) -> None:
        if not issubclass(self.configuration_class, BaseAuthenticatorConfiguration):
            raise TypeError("self.configuration_class must subclass BaseAuthenticatorConfiguration.")

        serializer = self.configuration_class(data=data)
        serializer.is_valid(raise_exception=True)

        allowed_fields = serializer.get_fields()
        errors = {}
        for k in data:
            if k not in allowed_fields:
                errors[k] = _(f"{k} is not a supported configuration option.")

        if errors:
            raise ValidationError(errors)

    def update_settings(self, database_authenticator: Authenticator) -> None:
        self.settings = database_authenticator.configuration

    def update_if_needed(self, database_authenticator: Authenticator) -> None:
        if not self.database_instance or self.database_instance.modified_on != database_authenticator.modified_on:
            if self.database_instance:
                self.logger.info(f"Updating {self.type} adapter {database_authenticator.name}")
            else:
                self.logger.info(f"Creating an {self.type} adapter from {database_authenticator.name}")
            self.database_instance = database_authenticator
            self.update_settings(database_authenticator)
        else:
            self.logger.info(f"No updated needed for {self.type} adapter {database_authenticator.name}")

    def get_default_attributes(self):
        """
        Each backend must return a list of common attributes that are available for the authenticator map.
        These values will  be queryable by the API so that the UI can help the user configure authenticator maps.

        This list won't be comprehensive since we may not know what's available until a user logs in.

        Users will be able to configure attributes which they know exist in the Authenticator model. Additionally,
        the list of available attributes returned to the api should include fields in AuthenticatorUser.extra
        once user's have started logging in with the authenticator.
        """
        raise NotImplementedError("Implement in subclass.")
