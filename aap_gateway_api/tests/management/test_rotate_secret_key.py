import io
import json
import logging
import os
import re
from unittest.mock import patch

import pytest
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from cryptography.fernet import InvalidToken
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from aap_gateway_api.utils.encryption import decrypt_with_key, encrypt_with_key

# ── Argument validation ─────────────────────────────────────────────────


@pytest.mark.django_db
def test_use_custom_key_requires_env_var():
    """CommandError when --use-custom-key is set without GATEWAY_SECRET_KEY."""
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("GATEWAY_SECRET_KEY", None)
        with pytest.raises(CommandError, match="GATEWAY_SECRET_KEY"):
            call_command("rotate_secret_key", use_custom_key=True)


@pytest.mark.django_db
def test_same_key_aborts(settings):
    """CommandError when the new key equals the current SECRET_KEY."""
    settings.SECRET_KEY = "identical-key"
    with patch.dict(os.environ, {"GATEWAY_SECRET_KEY": "identical-key"}):
        with pytest.raises(CommandError, match="identical"):
            call_command("rotate_secret_key", use_custom_key=True)


# ── Dry-run behaviour ───────────────────────────────────────────────────


@pytest.mark.django_db(transaction=True)
def test_dry_run_reports_without_writing(settings):
    """--dry-run reports affected rows but leaves ciphertext unchanged."""
    from aap_gateway_api.models import ServiceCluster, ServiceType

    st, _ = ServiceType.objects.get_or_create(name="controller")
    cluster = ServiceCluster.objects.create(name="dry-run-cluster", service_type=st)
    sk = cluster.generate_key(name="dry-run-key")

    with connection.cursor() as cur:
        cur.execute("SELECT secret FROM aap_gateway_api_servicekey WHERE id = %s", [sk.pk])
        old_cipher = cur.fetchone()[0]

    out = io.StringIO()
    with patch.dict(os.environ, {"GATEWAY_SECRET_KEY": "new-secret-for-dry-run"}):
        call_command("rotate_secret_key", use_custom_key=True, dry_run=True, stdout=out)

    assert "would be re-encrypted" in out.getvalue()

    with connection.cursor() as cur:
        cur.execute("SELECT secret FROM aap_gateway_api_servicekey WHERE id = %s", [sk.pk])
        after_cipher = cur.fetchone()[0]
    assert after_cipher == old_cipher


@pytest.mark.django_db
def test_dry_run_does_not_print_generated_key(settings):
    """--dry-run must not emit a generated key to avoid operator confusion."""
    settings.SECRET_KEY = "test-secret-dry-run-no-key"
    out = io.StringIO()
    call_command("rotate_secret_key", dry_run=True, stdout=out)

    lines = [ln for ln in out.getvalue().splitlines() if ln.strip()]
    for line in lines:
        assert "would be" in line or "cache" in line.lower()


# ── Full rotation ────────────────────────────────────────────────────────


@pytest.mark.django_db(transaction=True)
def test_service_key_rotation(settings):
    """ServiceKey.secret is re-encrypted with the new key."""
    new_key = "new-gw-rotation-key"

    from aap_gateway_api.models import ServiceCluster, ServiceType

    st, _ = ServiceType.objects.get_or_create(name="controller")
    cluster = ServiceCluster.objects.create(name="test-rotate-cluster", service_type=st)
    sk = cluster.generate_key(name="test-rotate-key")
    original_secret = sk.secret

    with connection.cursor() as cur:
        cur.execute("SELECT secret FROM aap_gateway_api_servicekey WHERE id = %s", [sk.pk])
        old_cipher = cur.fetchone()[0]

    assert ENCRYPTED_STRING in old_cipher

    out = io.StringIO()
    with patch.dict(os.environ, {"GATEWAY_SECRET_KEY": new_key}):
        call_command("rotate_secret_key", use_custom_key=True, stdout=out)

    with connection.cursor() as cur:
        cur.execute("SELECT secret FROM aap_gateway_api_servicekey WHERE id = %s", [sk.pk])
        new_cipher = cur.fetchone()[0]

    assert new_cipher != old_cipher
    assert decrypt_with_key(new_cipher, new_key) == original_secret


@pytest.mark.django_db(transaction=True)
def test_preference_rotation(settings):
    """Encrypted preference values are re-encrypted with the new key."""
    old_key = settings.SECRET_KEY
    new_key = "new-pref-rotation-key"

    from aap_gateway_api.models import Preference

    encrypted_val = encrypt_with_key("my-secret-pref-value", old_key)
    Preference.objects.update_or_create(
        section="analytics",
        name="REDHAT_PASSWORD",
        defaults={"raw_value": encrypted_val},
    )

    out = io.StringIO()
    with patch.dict(os.environ, {"GATEWAY_SECRET_KEY": new_key}):
        call_command("rotate_secret_key", use_custom_key=True, stdout=out)

    assert "re-encrypted" in out.getvalue()

    with connection.cursor() as cur:
        cur.execute(
            "SELECT raw_value FROM aap_gateway_api_preference WHERE section = %s AND name = %s",
            ["analytics", "REDHAT_PASSWORD"],
        )
        new_cipher = cur.fetchone()[0]

    assert new_cipher != encrypted_val
    assert decrypt_with_key(new_cipher, new_key) == "my-secret-pref-value"


@pytest.mark.django_db(transaction=True)
def test_authenticator_config_rotation(settings):
    """Authenticator.configuration encrypted sub-fields are re-encrypted."""

    from ansible_base.authentication.models import Authenticator

    new_key = "new-auth-config-key"

    authenticator = Authenticator.objects.create(
        name="Test OIDC Rotator",
        enabled=True,
        create_objects=True,
        type="ansible_base.authentication.authenticator_plugins.oidc",
        configuration={
            "ACCESS_TOKEN_URL": "https://idp.example.com/token",
            "AUTHORIZATION_URL": "https://idp.example.com/auth",
            "KEY": "my-client-id",
            "SECRET": "my-oidc-secret",
        },
    )

    qn = connection.ops.quote_name
    config_sql = "SELECT {config} FROM {table} WHERE {pk} = %s".format(
        config=qn("configuration"),
        table=qn(Authenticator._meta.db_table),
        pk=qn(Authenticator._meta.pk.column),
    )

    with connection.cursor() as cur:
        cur.execute(config_sql, [authenticator.pk])
        raw_before = cur.fetchone()[0]
    before = json.loads(raw_before) if isinstance(raw_before, str) else raw_before
    old_secret = before["SECRET"]
    assert ENCRYPTED_STRING in old_secret

    out = io.StringIO()
    with patch.dict(os.environ, {"GATEWAY_SECRET_KEY": new_key}):
        call_command("rotate_secret_key", use_custom_key=True, stdout=out)

    assert "re-encrypted" in out.getvalue()

    with connection.cursor() as cur:
        cur.execute(config_sql, [authenticator.pk])
        raw_after = cur.fetchone()[0]
    after = json.loads(raw_after) if isinstance(raw_after, str) else raw_after
    new_secret = after["SECRET"]
    assert ENCRYPTED_STRING in new_secret
    assert new_secret != old_secret
    assert decrypt_with_key(new_secret, new_key) == "my-oidc-secret"
    assert after["KEY"] == "my-client-id"


# ── Graceful skip on decryption failure ──────────────────────────────────


@pytest.mark.django_db(transaction=True)
def test_undecryptable_row_is_skipped(settings):
    """Rows encrypted with a different key are skipped without aborting."""
    old_key = settings.SECRET_KEY
    new_key = "new-skip-test-key"
    wrong_key = "completely-different-key"

    good_cipher = encrypt_with_key("good-value", old_key)
    bad_cipher = encrypt_with_key("bad-value", wrong_key)

    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO aap_gateway_api_preference (section, name, raw_value) VALUES (%s, %s, %s)"
            " ON CONFLICT (section, name) DO UPDATE SET raw_value = EXCLUDED.raw_value",
            ["test_skip", "good_pref", good_cipher],
        )
        cur.execute(
            "INSERT INTO aap_gateway_api_preference (section, name, raw_value) VALUES (%s, %s, %s)"
            " ON CONFLICT (section, name) DO UPDATE SET raw_value = EXCLUDED.raw_value",
            ["test_skip", "bad_pref", bad_cipher],
        )

    out = io.StringIO()
    err = io.StringIO()
    with patch.dict(os.environ, {"GATEWAY_SECRET_KEY": new_key}):
        call_command("rotate_secret_key", use_custom_key=True, stdout=out, stderr=err)

    assert "re-encrypted" in out.getvalue()

    warning = err.getvalue()
    assert "could not be decrypted" in warning
    assert "old SECRET_KEY must be preserved" in warning

    with connection.cursor() as cur:
        cur.execute(
            "SELECT raw_value FROM aap_gateway_api_preference WHERE section = %s AND name = %s",
            ["test_skip", "bad_pref"],
        )
        bad_after = cur.fetchone()[0]
    assert bad_after == bad_cipher

    with connection.cursor() as cur:
        cur.execute(
            "SELECT raw_value FROM aap_gateway_api_preference WHERE section = %s AND name = %s",
            ["test_skip", "good_pref"],
        )
        good_after = cur.fetchone()[0]
    assert good_after != good_cipher
    assert decrypt_with_key(good_after, new_key) == "good-value"


# ── Auto-generated key ──────────────────────────────────────────────────


@pytest.mark.django_db(transaction=True)
def test_auto_generated_key_printed_once(settings):
    """When no custom key is provided, a generated key is printed exactly once."""
    settings.SECRET_KEY = "old-key-auto-gen"

    out = io.StringIO()
    call_command("rotate_secret_key", stdout=out)

    output = out.getvalue()
    lines = [ln for ln in output.splitlines() if ln.strip()]
    assert any("re-encrypted" in ln for ln in lines)
    key_candidates = [ln for ln in lines if not re.search(r"re-encrypted|cache", ln, re.IGNORECASE)]
    assert len(key_candidates) == 1, f"Expected exactly one key line, got: {key_candidates}"
    key_line = key_candidates[0]
    assert len(key_line) > 10
    assert output.count(key_line) == 1


# ── Cache flush ──────────────────────────────────────────────────────────


@pytest.mark.django_db(transaction=True)
def test_cache_flush_message_dry_run(settings):
    """--dry-run reports that the preference cache would be flushed."""
    out = io.StringIO()
    with patch.dict(os.environ, {"GATEWAY_SECRET_KEY": "new-key-cache-dry"}):
        call_command("rotate_secret_key", use_custom_key=True, dry_run=True, stdout=out)
    assert "cache" in out.getvalue().lower()


@pytest.mark.django_db(transaction=True)
def test_cache_flush_message_normal(settings):
    """Normal mode reports that the preference cache was flushed."""
    out = io.StringIO()
    with patch.dict(os.environ, {"GATEWAY_SECRET_KEY": "new-key-cache-normal"}):
        call_command("rotate_secret_key", use_custom_key=True, stdout=out)
    assert "cache" in out.getvalue().lower()


# ── Defensive path coverage ──────────────────────────────────────────────


@pytest.mark.django_db
def test_parse_config_malformed_json():
    """_parse_config returns None for malformed JSON strings."""
    from aap_gateway_api.management.commands.rotate_secret_key import Command

    assert Command._parse_config("not-valid-json{") is None
    assert Command._parse_config("") is None
    assert Command._parse_config(None) is None
    assert Command._parse_config(42) is None
    assert Command._parse_config({"key": "val"}) == {"key": "val"}
    assert Command._parse_config('{"key": "val"}') == {"key": "val"}


@pytest.mark.django_db(transaction=True)
def test_jsonb_encrypted_field_rotation(settings):
    """Encrypted fields stored in jsonb columns are correctly rotated.

    This covers AuthenticatorUser.extra_data and similar JSONField-backed
    encrypted fields. The encrypted ciphertext is stored as a JSON string
    inside the jsonb column, which psycopg may return already-unwrapped
    (as a Python str) or still JSON-encoded (with outer quotes).
    """
    from ansible_base.authentication.models import Authenticator
    from django.contrib.auth import get_user_model

    User = get_user_model()

    old_key = settings.SECRET_KEY
    new_key = "new-jsonb-rotation-key"

    authenticator = Authenticator.objects.create(
        name="Test LDAP for jsonb",
        enabled=True,
        create_objects=True,
        type="ansible_base.authentication.authenticator_plugins.ldap",
        configuration={},
    )

    user = User.objects.create_user(username="jsonb-test-user", password="test")

    extra_data = {"sub": "user123", "groups": ["admin", "dev"], "token": "secret-token-value"}
    encrypted_extra = encrypt_with_key(extra_data, old_key)

    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO dab_authentication_authenticatoruser "
            "(provider_id, uid, user_id, extra_data, claims, last_login_map_results, access_allowed, created, modified) "
            "VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, NOW(), NOW())",
            [authenticator.slug, "jsonb-test-uid", user.pk, json.dumps(encrypted_extra), '{}', '[]', True],
        )

    with connection.cursor() as cur:
        cur.execute("SELECT extra_data FROM dab_authentication_authenticatoruser WHERE uid = %s", ["jsonb-test-uid"])
        raw_before = cur.fetchone()[0]

    assert ENCRYPTED_STRING in str(raw_before)

    out = io.StringIO()
    with patch.dict(os.environ, {"GATEWAY_SECRET_KEY": new_key}):
        call_command("rotate_secret_key", use_custom_key=True, stdout=out)

    assert "re-encrypted" in out.getvalue()

    with connection.cursor() as cur:
        cur.execute("SELECT extra_data FROM dab_authentication_authenticatoruser WHERE uid = %s", ["jsonb-test-uid"])
        raw_after = cur.fetchone()[0]

    raw_after_str = raw_after if isinstance(raw_after, str) else json.dumps(raw_after)
    if raw_after_str.startswith('"'):
        raw_after_str = json.loads(raw_after_str)

    assert ENCRYPTED_STRING in raw_after_str
    assert raw_after_str != encrypted_extra
    assert decrypt_with_key(raw_after_str, new_key) == extra_data


@pytest.mark.django_db(transaction=True)
def test_jsonb_encrypted_field_with_json_wrapped_value(settings):
    """Rotation handles jsonb values returned with JSON string wrapping.

    Simulates the case where psycopg returns a jsonb string value still
    wrapped in JSON quotes (e.g. '"$encrypted$..."' instead of
    '$encrypted$...').
    """
    from aap_gateway_api.management.commands.rotate_secret_key import Command

    old_key = settings.SECRET_KEY
    new_key = "new-jsonb-wrapped-key"

    cmd = Command()
    cmd.old_key = old_key
    cmd.new_key = new_key
    cmd._skipped_count = 0

    original_data = {"secret": "my-secret-value"}
    encrypted = encrypt_with_key(original_data, old_key)

    json_wrapped = json.dumps(encrypted)
    result = cmd._reencrypt_value(json_wrapped, label="test-wrapped", is_jsonb=True)
    assert result is not None

    inner = json.loads(result)
    assert ENCRYPTED_STRING in inner
    assert decrypt_with_key(inner, new_key) == original_data

    result_unwrapped = cmd._reencrypt_value(encrypted, label="test-unwrapped", is_jsonb=True)
    assert result_unwrapped is not None
    inner2 = json.loads(result_unwrapped)
    assert decrypt_with_key(inner2, new_key) == original_data


@pytest.mark.django_db
def test_normalise_jsonb_value():
    """_normalise_jsonb_value correctly unwraps various jsonb representations."""
    from aap_gateway_api.management.commands.rotate_secret_key import Command

    encrypted = "$encrypted$UTF8$AESCBC$base64data"

    assert Command._normalise_jsonb_value(encrypted) == encrypted

    json_wrapped = json.dumps(encrypted)
    assert Command._normalise_jsonb_value(json_wrapped) == encrypted

    assert Command._normalise_jsonb_value({"key": "value"}) is None
    assert Command._normalise_jsonb_value([1, 2, 3]) is None
    assert Command._normalise_jsonb_value(None) is None

    # Non-JSON string that doesn't start with $encrypted$ falls through to return raw
    assert Command._normalise_jsonb_value("plain-text-not-json") == "plain-text-not-json"

    # Invalid JSON triggers the except branch and returns raw
    assert Command._normalise_jsonb_value("{invalid json{{") == "{invalid json{{"

    # A JSON-parseable value that isn't a string (e.g. a number) returns raw
    assert Command._normalise_jsonb_value("42") == "42"


@pytest.mark.django_db
def test_reencrypt_value_jsonb_empty_and_non_string(settings):
    """_reencrypt_value returns None for empty or non-string jsonb values."""
    from aap_gateway_api.management.commands.rotate_secret_key import Command

    cmd = Command()
    cmd.old_key = settings.SECRET_KEY
    cmd.new_key = "test-coverage-key"
    cmd._skipped_count = 0

    # Empty/None raw value with is_jsonb=True
    assert cmd._reencrypt_value(None, label="test-none", is_jsonb=True) is None
    assert cmd._reencrypt_value("", label="test-empty", is_jsonb=True) is None

    # Non-string jsonb value (dict) that _normalise_jsonb_value returns None for
    assert cmd._reencrypt_value({"key": "value"}, label="test-dict", is_jsonb=True) is None

    # Plain string without encrypted marker
    assert cmd._reencrypt_value("not-encrypted", label="test-plain", is_jsonb=True) is None


@pytest.mark.django_db
def test_rotate_encrypted_fields_skips_missing_field(settings, caplog):
    """Fields listed in encrypted_fields but missing from the model are skipped."""
    from aap_gateway_api.management.commands.rotate_secret_key import Command
    from aap_gateway_api.models import ServiceCluster

    cmd = Command()
    cmd.old_key = settings.SECRET_KEY
    cmd.new_key = "test-field-not-exist-key"
    cmd._skipped_count = 0

    with caplog.at_level(logging.WARNING, logger="aap.gateway.management.rotate_secret_key"):
        with patch(
            "aap_gateway_api.management.commands.rotate_secret_key._iter_models_with_encrypted_fields",
            return_value=[(ServiceCluster, ["nonexistent_field_xyz"])],
        ):
            total = cmd._rotate_encrypted_fields(dry_run=False)

    assert total == 0
    assert "nonexistent_field_xyz" in caplog.text


@pytest.mark.django_db(transaction=True)
def test_flush_preference_cache_failure_is_graceful(settings, caplog):
    """_flush_preference_cache logs a warning instead of crashing when the cache is unavailable."""
    from aap_gateway_api.management.commands.rotate_secret_key import Command

    cmd = Command()

    with caplog.at_level(logging.WARNING, logger="aap.gateway.management.rotate_secret_key"):
        with patch("aap_gateway_api.preferences.gateway_preference_registry") as mock_registry:
            mock_registry.manager.side_effect = RuntimeError("cache unavailable")
            cmd._flush_preference_cache(dry_run=False)

    assert "Could not clear preference cache" in caplog.text


# ── Encryption helper unit tests ─────────────────────────────────────────


class TestEncryptionHelpers:
    """Unit tests for the gateway-local encryption helpers."""

    def test_round_trip(self):
        """Encrypt then decrypt returns the original value."""
        key = "my-custom-key-material"
        encrypted = encrypt_with_key("hello-world", key)
        assert ENCRYPTED_STRING in encrypted
        assert decrypt_with_key(encrypted, key) == "hello-world"

    def test_different_keys_produce_different_ciphertext(self):
        """Same plaintext encrypted with different keys yields different ciphertext."""
        val = "same-value"
        enc1 = encrypt_with_key(val, "key-one")
        enc2 = encrypt_with_key(val, "key-two")
        assert enc1 != enc2

    def test_wrong_key_fails(self):
        """Decryption with the wrong key raises InvalidToken."""
        encrypted = encrypt_with_key("secret", "correct-key")
        with pytest.raises(InvalidToken):
            decrypt_with_key(encrypted, "wrong-key")

    def test_decrypt_rejects_non_encrypted_input(self):
        """decrypt_with_key raises ValueError for input without the encrypted marker."""
        with pytest.raises(ValueError, match="does not start with"):
            decrypt_with_key("plain-text-value", "any-key")

    def test_json_types_preserved(self):
        """JSON-serialisable types survive an encrypt/decrypt round trip."""
        key = "test-json-key"
        for val in ["string", 42, True, None, {"nested": "dict"}, [1, 2, 3]]:
            encrypted = encrypt_with_key(val, key)
            assert decrypt_with_key(encrypted, key) == val

    def test_rewrap_with_new_key(self):
        """Decrypt with old key, re-encrypt with new key, verify both directions."""
        old_k = "old-key-material"
        new_k = "new-key-material"
        value = "credential-payload"

        ciphertext = encrypt_with_key(value, old_k)
        assert decrypt_with_key(ciphertext, old_k) == value

        with pytest.raises(InvalidToken):
            decrypt_with_key(ciphertext, new_k)

        rewrapped = encrypt_with_key(decrypt_with_key(ciphertext, old_k), new_k)
        assert decrypt_with_key(rewrapped, new_k) == value

        with pytest.raises(InvalidToken):
            decrypt_with_key(rewrapped, old_k)
