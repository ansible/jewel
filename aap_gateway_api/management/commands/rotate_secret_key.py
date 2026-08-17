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
from django.db import connection, transaction
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
                is_jsonb = isinstance(field_obj, JSONField)
                total += self._reencrypt_column(model, field_obj.column, dry_run, is_jsonb=is_jsonb)
        return total

    # ── Authenticator.configuration encrypted sub-fields ─────────────────

    def _rotate_authenticator_configs(self, dry_run: bool) -> int:
        total = 0
        select_sql = self._build_authenticator_select_sql()
        update_sql = self._build_authenticator_update_sql()

        with connection.cursor() as cur:
            cur.execute(select_sql)
            rows = cur.fetchall()

        for pk, auth_type, config in rows:
            config = self._parse_config(config)
            if config is None:
                continue
            changed, field_count = self._reencrypt_authenticator_fields(pk, auth_type, config)
            total += field_count
            if changed and not dry_run:
                with connection.cursor() as ucur:
                    ucur.execute(update_sql, [json.dumps(config), pk])
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

    @staticmethod
    def _build_authenticator_select_sql() -> str:
        """Build SELECT for authenticator config scanning.

        Safe from SQL injection: all identifiers originate from Django
        model metadata and are quoted via the database backend.
        """
        qn = connection.ops.quote_name
        return "SELECT {pk}, {type}, {config} FROM {table}".format(
            pk=qn(Authenticator._meta.pk.column),
            type=qn(Authenticator._meta.get_field('type').column),
            config=qn(Authenticator._meta.get_field('configuration').column),
            table=qn(Authenticator._meta.db_table),
        )

    @staticmethod
    def _build_authenticator_update_sql() -> str:
        """Build UPDATE for authenticator config re-encryption.

        Uses the PostgreSQL-specific ``::jsonb`` cast to ensure the text
        parameter is stored correctly in the ``jsonb`` column.  This is
        not portable to SQLite or MySQL, but the gateway requires
        PostgreSQL in both production and test environments.

        Safe from SQL injection: all identifiers originate from Django
        model metadata and are quoted via the database backend.
        """
        qn = connection.ops.quote_name
        return "UPDATE {table} SET {config} = %s::jsonb WHERE {pk} = %s".format(
            table=qn(Authenticator._meta.db_table),
            config=qn(Authenticator._meta.get_field('configuration').column),
            pk=qn(Authenticator._meta.pk.column),
        )

    # ── Preference rows (encrypted=True) ─────────────────────────────────

    def _rotate_preferences(self, dry_run: bool) -> int:
        from aap_gateway_api.models import Preference

        first_page_sql = self._build_preference_select_sql(Preference, with_pk_bound=False)
        next_page_sql = self._build_preference_select_sql(Preference, with_pk_bound=True)
        update_sql = self._build_preference_update_sql(Preference)
        return self._paginated_reencrypt(first_page_sql, next_page_sql, update_sql, dry_run, label="Preference")

    @staticmethod
    def _build_preference_select_sql(model, *, with_pk_bound: bool) -> str:
        """Build paginated SELECT for preference scanning.

        When *with_pk_bound* is ``True`` the query includes a
        ``WHERE ... AND pk > %s`` predicate for keyset pagination.
        The first page is fetched without this predicate so no
        assumption about the PK type is needed.

        Safe from SQL injection: all identifiers originate from Django
        model metadata and are quoted via the database backend.
        """
        qn = connection.ops.quote_name
        pk = qn(model._meta.pk.column)
        val = qn('raw_value')
        table = qn(model._meta.db_table)

        pk_clause = "AND {pk} > %s ".format(pk=pk) if with_pk_bound else ""
        return "SELECT {pk}, {val} FROM {table} WHERE {val} IS NOT NULL {pk_clause}ORDER BY {pk} LIMIT {limit}".format(
            pk=pk,
            val=val,
            table=table,
            pk_clause=pk_clause,
            limit=_FETCH_BATCH_SIZE,
        )

    @staticmethod
    def _build_preference_update_sql(model) -> str:
        """Build UPDATE for preference re-encryption.

        Safe from SQL injection: all identifiers originate from Django
        model metadata and are quoted via the database backend.
        """
        qn = connection.ops.quote_name
        return "UPDATE {table} SET {val} = %s WHERE {pk} = %s".format(
            table=qn(model._meta.db_table),
            val=qn('raw_value'),
            pk=qn(model._meta.pk.column),
        )

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

    def _paginated_reencrypt(self, first_page_sql: str, next_page_sql: str, update_sql: str, dry_run: bool, *, label: str, is_jsonb: bool = False) -> int:
        """Paginate through rows and re-encrypt values.

        Used by both ``_reencrypt_column`` and ``_rotate_preferences``
        to avoid duplicating the pagination and per-row re-encryption
        logic.
        """
        count = 0
        last_pk = None
        while True:
            with connection.cursor() as cur:
                if last_pk is None:
                    cur.execute(first_page_sql)
                else:
                    cur.execute(next_page_sql, [last_pk])
                rows = cur.fetchall()
            if not rows:
                break
            last_pk = rows[-1][0]
            for pk, raw in rows:
                normalised = self._normalise_if_jsonb_value(raw)
                new_val = self._reencrypt_value(normalised, label=f"{label} pk={pk}")
                if new_val is None:
                    continue
                if not dry_run:
                    write_val = json.dumps(new_val) if is_jsonb else new_val
                    with connection.cursor() as ucur:
                        ucur.execute(update_sql, [write_val, pk])
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

    @staticmethod
    def _build_column_select_sql(model, column_name, *, with_pk_bound: bool) -> str:
        """Build a paginated SELECT for encrypted column scanning.

        When *with_pk_bound* is ``True`` the query includes a
        ``WHERE pk > %s`` predicate for keyset pagination.  The first
        page is fetched without this predicate so no assumption about
        the PK type (integer vs UUID) is needed.

        Safe from SQL injection: all identifiers originate from Django
        model metadata and are quoted via the database backend.
        """
        qn = connection.ops.quote_name
        pk = qn(model._meta.pk.column)
        col = qn(column_name)
        table = qn(model._meta.db_table)

        pk_clause = "AND {pk} > %s ".format(pk=pk) if with_pk_bound else ""
        return "SELECT {pk}, {col} FROM {table} WHERE {col} IS NOT NULL {pk_clause}ORDER BY {pk} LIMIT {limit}".format(
            pk=pk,
            col=col,
            table=table,
            pk_clause=pk_clause,
            limit=_FETCH_BATCH_SIZE,
        )

    @staticmethod
    def _build_column_update_sql(model, column_name, *, is_jsonb: bool = False) -> str:
        """Build an UPDATE query for re-encrypting a single row.

        When *is_jsonb* is ``True``, the value parameter is cast to
        ``jsonb`` so PostgreSQL correctly stores it in a jsonb column.

        Safe from SQL injection: all identifiers originate from Django
        model metadata and are quoted via the database backend.
        """
        qn = connection.ops.quote_name
        cast = "::jsonb" if is_jsonb else ""
        return "UPDATE {table} SET {col} = %s{cast} WHERE {pk} = %s".format(
            table=qn(model._meta.db_table),
            col=qn(column_name),
            pk=qn(model._meta.pk.column),
            cast=cast,
        )

    def _reencrypt_column(self, model, column_name: str, dry_run: bool, *, is_jsonb: bool = False) -> int:
        first_page_sql = self._build_column_select_sql(model, column_name, with_pk_bound=False)
        next_page_sql = self._build_column_select_sql(model, column_name, with_pk_bound=True)
        update_sql = self._build_column_update_sql(model, column_name, is_jsonb=is_jsonb)
        label = f"{model.__name__}.{column_name}"
        return self._paginated_reencrypt(first_page_sql, next_page_sql, update_sql, dry_run, label=label, is_jsonb=is_jsonb)
