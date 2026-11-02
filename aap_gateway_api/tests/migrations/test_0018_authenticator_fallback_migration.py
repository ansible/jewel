import importlib

from ansible_base.authentication.models import Authenticator
from django.apps import apps

_migration = importlib.import_module("aap_gateway_api.migrations.0018_remove_controller_fallback_from_local_authenticators")
remove_fallback = _migration.remove_fallback_authentication_from_local_authenticators
restore_fallback = _migration.add_fallback_authentication_to_local_authenticators

LOCAL_TYPE = "ansible_base.authentication.authenticator_plugins.local"
REMOTE_TYPE = "ansible_base.authentication.authenticator_plugins.ldap"
CONTROLLER_FALLBACK = "aap_gateway_api.authentication.fallbacks.controller"


def create_authenticator(name, *, authenticator_type=LOCAL_TYPE, configuration=None):
    return Authenticator.objects.create(
        name=name,
        type=authenticator_type,
        enabled=True,
        configuration={} if configuration is None else configuration,
    )


def test_forward_removes_only_local_fallback_and_preserves_other_configuration(db):
    with_fallback = create_authenticator(
        "Snapshot Local With Fallback",
        configuration={"fallback_authentication": [CONTROLLER_FALLBACK], "custom": {"enabled": True}},
    )
    empty_local = create_authenticator("Snapshot Empty Local", configuration={})
    custom_fallback = create_authenticator(
        "Snapshot Custom Fallback",
        configuration={"fallback_authentication": [], "other": "preserve"},
    )
    remote_authenticator = create_authenticator(
        "Snapshot Remote",
        authenticator_type=REMOTE_TYPE,
        configuration={"fallback_authentication": [CONTROLLER_FALLBACK], "remote_setting": "preserve"},
    )

    remove_fallback(apps, None)
    for authenticator in (with_fallback, empty_local, custom_fallback, remote_authenticator):
        authenticator.refresh_from_db()

    assert {"custom": {"enabled": True}} == with_fallback.configuration
    assert {} == empty_local.configuration
    assert {"other": "preserve"} == custom_fallback.configuration
    assert {"fallback_authentication": [CONTROLLER_FALLBACK], "remote_setting": "preserve"} == remote_authenticator.configuration

    first_run = {auth.pk: (auth.configuration, auth.modified) for auth in (with_fallback, empty_local, custom_fallback, remote_authenticator)}
    remove_fallback(apps, None)
    for authenticator in (with_fallback, empty_local, custom_fallback, remote_authenticator):
        authenticator.refresh_from_db()
        assert (authenticator.configuration, authenticator.modified) == first_run[authenticator.pk]


def test_reverse_adds_default_once_and_preserves_existing_fallbacks(db):
    missing_fallback = create_authenticator("Snapshot Missing Fallback", configuration={"custom": "keep"})
    existing_fallback = create_authenticator(
        "Snapshot Existing Fallback",
        configuration={"fallback_authentication": [], "custom": "keep"},
    )
    remote_authenticator = create_authenticator(
        "Snapshot Remote Reverse",
        authenticator_type=REMOTE_TYPE,
        configuration={"custom": "keep"},
    )

    restore_fallback(apps, None)
    for authenticator in (missing_fallback, existing_fallback, remote_authenticator):
        authenticator.refresh_from_db()

    assert {"custom": "keep", "fallback_authentication": [CONTROLLER_FALLBACK]} == missing_fallback.configuration
    assert {"fallback_authentication": [], "custom": "keep"} == existing_fallback.configuration
    assert {"custom": "keep"} == remote_authenticator.configuration

    first_run = {auth.pk: (auth.configuration, auth.modified) for auth in (missing_fallback, existing_fallback, remote_authenticator)}
    restore_fallback(apps, None)
    for authenticator in (missing_fallback, existing_fallback, remote_authenticator):
        authenticator.refresh_from_db()
        assert (authenticator.configuration, authenticator.modified) == first_run[authenticator.pk]
        assert authenticator.configuration.get("fallback_authentication", []).count(CONTROLLER_FALLBACK) <= 1
