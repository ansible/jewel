import io
import os
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
    key_line = lines[-1]
    assert len(key_line) > 10
    assert output.count(key_line) == 1


# ── Cache flush ──────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_cache_flush_message(settings):
    """The command reports cache flushing in both dry-run and normal modes."""
    settings.SECRET_KEY = "test-cache-flush-key"
    out = io.StringIO()
    with patch.dict(os.environ, {"GATEWAY_SECRET_KEY": "new-key-cache"}):
        call_command("rotate_secret_key", use_custom_key=True, dry_run=True, stdout=out)
    assert "cache" in out.getvalue().lower()


# ── Encryption helper unit tests ─────────────────────────────────────────


class TestEncryptionHelpers:
    def test_round_trip(self):
        key = "my-custom-key-material"
        encrypted = encrypt_with_key("hello-world", key)
        assert ENCRYPTED_STRING in encrypted
        assert decrypt_with_key(encrypted, key) == "hello-world"

    def test_different_keys_produce_different_ciphertext(self):
        val = "same-value"
        enc1 = encrypt_with_key(val, "key-one")
        enc2 = encrypt_with_key(val, "key-two")
        assert enc1 != enc2

    def test_wrong_key_fails(self):
        encrypted = encrypt_with_key("secret", "correct-key")
        with pytest.raises(InvalidToken):
            decrypt_with_key(encrypted, "wrong-key")

    def test_json_types_preserved(self):
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
