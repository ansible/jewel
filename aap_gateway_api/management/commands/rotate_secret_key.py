r"""Re-encrypt all gateway-managed secrets after changing SECRET_KEY.

Handles all encrypted data in the gateway database:

* ``AbstractCommonModel.encrypted_fields`` columns (e.g. ``ServiceKey.secret``)
* ``Authenticator.configuration`` sub-fields marked as encrypted by each
  authenticator plugin
* ``Preference`` rows stored with ``encrypted=True``
* Preference cache (flushed so stale ciphertext is not served)

Mirrors the operational pattern of ``awx-manage regenerate_secret_key``
(Automation Controller) and ``aap-eda-manage rotate_db_encryption_key``
(EDA Server): stop traffic, run the command, update the deployment secret
with the new key, then restart services.

Usage::

    gateway-manage rotate_secret_key
    GATEWAY_SECRET_KEY='...' \
      gateway-manage rotate_secret_key --use-custom-key
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Iterator

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugin
from ansible_base.authentication.models import Authenticator
from ansible_base.lib.abstract_models.common import AbstractCommonModel
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from cryptography.fernet import InvalidToken
from django.apps import apps
from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import JSONField

from aap_gateway_api.utils.encryption import decrypt_with_key, encrypt_with_key

logger = logging.getLogger('aap.gateway.management.rotate_secret_key')

_FETCH_BATCH_SIZE = 2000


def _iter_models_with_encrypted_fields() -> Iterator[tuple[type, list[str]]]:
    """Yield ``(model_class, field_names)`` for every model with non-empty encrypted_fields.

    Only yields fields defined directly on the model (not inherited)
    to avoid processing the same column twice in multi-table
    inheritance hierarchies.
    """
    for model in apps.get_models():
        if not issubclass(model, AbstractCommonModel):
            continue
        fields = getattr(model, 'encrypted_fields', [])
        if not fields:
            continue
        local_field_names = {f.name for f in model._meta.local_fields}
        own_fields = [f for f in fields if f in local_field_names]
        if own_fields:
            yield model, own_fields


class Command(BaseCommand):
    """Re-encrypt every secret in the gateway database with a new SECRET_KEY.

    The entire re-encryption runs inside a single database transaction so
    that a failure at any point rolls back all changes automatically.
    """

    help = (
        "Re-encrypt all gateway database secrets after rotating SECRET_KEY. "
        "Covers encrypted model fields, Authenticator config, and Preferences. "
        "Workflow: stop traffic, run this command, update the deployment secret "
        "with the printed key, then restart services."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--use-custom-key',
            dest='use_custom_key',
            action='store_true',
            default=False,
            help="Use the key from the GATEWAY_SECRET_KEY environment variable instead of generating a new one.",
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help="Report affected rows without writing to the database.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        use_custom_key: bool = options['use_custom_key']
        dry_run: bool = options['dry_run']

        self.old_key = settings.SECRET_KEY

        if use_custom_key:
            self.new_key = os.environ.get('GATEWAY_SECRET_KEY')
            if not self.new_key:
                raise CommandError("--use-custom-key was specified but GATEWAY_SECRET_KEY is not set in the environment.")
        else:
            self.new_key = base64.encodebytes(os.urandom(33)).decode().rstrip()

        if self.new_key == self.old_key:
            raise CommandError("New encryption key is identical to the current SECRET_KEY; rotation aborted.")

        self._skipped_count = 0

        total = 0
        total += self._rotate_encrypted_fields(dry_run)
        total += self._rotate_authenticator_configs(dry_run)
        total += self._rotate_preferences(dry_run)

        self._flush_preference_cache(dry_run)

        if dry_run:
            self.stdout.write(f"{total} value(s) would be re-encrypted.")
            self.stdout.write("Preference cache would be flushed.")
        else:
            self.stdout.write(f"{total} value(s) re-encrypted.")
            self.stdout.write("Preference cache flushed.")

        if self._skipped_count > 0:
            self.stderr.write(
                self.style.WARNING(
                    f"WARNING: {self._skipped_count} value(s) could not be decrypted "
                    f"and were NOT re-encrypted. The old SECRET_KEY must be preserved "
                    f"for these rows. See log for details."
                )
            )

        if not dry_run and not use_custom_key:
            self.stdout.write(self.new_key)

    # ── encrypted_fields on AbstractCommonModel subclasses ───────────────

    def _rotate_encrypted_fields(self, dry_run: bool) -> int:
        total = 0
        for model, field_names in _iter_models_with_encrypted_fields():
            for field_name in field_names:
                try:
                    field_obj = model._meta.get_field(field_name)
                except FieldDoesNotExist:
                    logger.warning("Model %s declares encrypted field %r but has no such DB column", model.__name__, field_name)
                    continue
                is_json_field = isinstance(field_obj, JSONField)
                total += self._reencrypt_column(model, field_obj.name, dry_run, is_json_field=is_json_field)
        return total

    # ── Authenticator.configuration encrypted sub-fields ─────────────────

    def _rotate_authenticator_configs(self, dry_run: bool) -> int:
        total = 0
        rows = list(Authenticator.objects.values_list("pk", "type", "configuration"))
        for pk, auth_type, config in rows:
            config = self._parse_config(config)
            if config is None:
                continue
            changed, field_count = self._reencrypt_authenticator_fields(pk, auth_type, config)
            total += field_count
            if changed and not dry_run:
                Authenticator.objects.filter(pk=pk).update(configuration=config)
        return total

    @staticmethod
    def _parse_config(config) -> dict | None:
        """Normalise a configuration value to a dict, or ``None`` if unusable."""
        if not config:
            return None
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except json.JSONDecodeError:
                return None
        return config if isinstance(config, dict) else None

    def _reencrypt_authenticator_fields(self, pk, auth_type: str, config: dict) -> tuple[bool, int]:
        """Re-encrypt encrypted sub-fields within a single authenticator's configuration.

        Returns ``(changed, field_count)`` where *changed* is ``True``
        if any field was modified and *field_count* is the number of
        fields re-encrypted.
        """
        try:
            plugin = get_authenticator_plugin(auth_type)
        except Exception:
            logger.warning("Cannot load plugin %r for Authenticator pk=%s; skipping", auth_type, pk)
            return False, 0
        encrypted_fields = getattr(plugin, 'configuration_encrypted_fields', [])
        changed = False
        count = 0
        for field in encrypted_fields:
            val = config.get(field)
            if not val or not isinstance(val, str) or ENCRYPTED_STRING not in val:
                continue
            clear = self._try_decrypt(val, label=f"Authenticator pk={pk} field {field!r}")
            if clear is None:
                continue
            config[field] = encrypt_with_key(clear, self.new_key)
            changed = True
            count += 1
        return changed, count

    # ── Preference rows (encrypted=True) ─────────────────────────────────

    def _rotate_preferences(self, dry_run: bool) -> int:
        from aap_gateway_api.models import Preference

        return self._paginated_reencrypt(Preference, "raw_value", dry_run, label="Preference")

    # ── Cache flush ──────────────────────────────────────────────────────

    def _flush_preference_cache(self, dry_run: bool) -> None:
        """Clear the preference cache so stale encrypted values are not served."""
        if dry_run:
            return
        try:
            from aap_gateway_api.preferences import gateway_preference_registry

            manager = gateway_preference_registry.manager()
            if hasattr(manager, 'cache'):
                manager.cache.clear()
                logger.info("Preference cache cleared after secret key rotation.")
        except Exception:
            logger.warning("Could not clear preference cache; manual cache flush may be needed.", exc_info=True)

    # ── Shared helpers ──────────────────────────────────────────────────

    def _try_decrypt(self, value: str, *, label: str):
        """Attempt to decrypt *value* with the old key, returning the cleartext or ``None``.

        Only catches ``InvalidToken`` (wrong key) and ``ValueError``
        (malformed ciphertext format).  Any other exception is a
        programming error and is allowed to propagate, rolling back the
        ``@transaction.atomic`` block.
        """
        try:
            return decrypt_with_key(value, self.old_key)
        except (InvalidToken, ValueError):
            logger.warning("Cannot decrypt %s with the current SECRET_KEY; skipping", label)
            self._skipped_count += 1
            return None

    def _paginated_reencrypt(self, model, field_name: str, dry_run: bool, *, label: str, is_json_field: bool = False) -> int:
        """Paginate through a model field and re-encrypt its values."""
        count = 0
        last_pk = None
        while True:
            page = model.objects.filter(**{f"{field_name}__isnull": False}).order_by("pk")
            if last_pk is not None:
                page = page.filter(pk__gt=last_pk)
            rows = list(page.values_list("pk", field_name)[:_FETCH_BATCH_SIZE])
            if not rows:
                break
            last_pk = rows[-1][0]
            count += self._reencrypt_rows(model, field_name, rows, dry_run, label=label, is_json_field=is_json_field)
        return count

    def _reencrypt_rows(self, model, field_name: str, rows: list, dry_run: bool, *, label: str, is_json_field: bool) -> int:
        """Normalise, re-encrypt, and persist a batch of rows."""
        count = 0
        for pk, raw in rows:
            normalised = self._normalise_if_jsonb_value(raw) if is_json_field else raw
            new_val = self._reencrypt_value(normalised, label=f"{label} pk={pk}")
            if new_val is None:
                continue
            if not dry_run:
                model.objects.filter(pk=pk).update(**{field_name: new_val})
            count += 1
        return count

    def _reencrypt_value(self, raw, *, label: str) -> str | None:
        """Decrypt a single value with the old key and re-encrypt with the new key.

        Returns the new ciphertext, or ``None`` if the value is not
        encrypted or cannot be decrypted.  This method is format-agnostic;
        callers handle input normalization and output serialization.
        """
        if not raw or not isinstance(raw, str) or ENCRYPTED_STRING not in raw:
            return None

        clear = self._try_decrypt(raw, label=label)
        if clear is None:
            return None

        return encrypt_with_key(clear, self.new_key)

    @staticmethod
    def _normalise_if_jsonb_value(raw) -> str | None:
        """Unwrap a value that may be JSON-encoded into a plain Python string.

        Safe to call on non-jsonb values: a plain string that isn't valid
        JSON is returned as-is.

        Depending on the psycopg adapter version and Django configuration,
        a jsonb column storing a JSON string may be returned as:
        * A Python ``str`` already unwrapped (psycopg2/3 with JSON adapter)
        * A Python ``str`` still JSON-encoded with outer quotes
        * A Python ``dict`` or other JSON-parsed type (if the stored value
          was a JSON object rather than a JSON string)
        """
        if not isinstance(raw, str):
            return None
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, str):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        return raw

    # ── SQL builders ─────────────────────────────────────────────────────

    def _reencrypt_column(self, model, field_name: str, dry_run: bool, *, is_json_field: bool = False) -> int:
        label = f"{model.__name__}.{field_name}"
        return self._paginated_reencrypt(model, field_name, dry_run, label=label, is_json_field=is_json_field)
