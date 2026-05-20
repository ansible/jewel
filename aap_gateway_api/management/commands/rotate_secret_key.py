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
from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

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

    help = "Re-encrypt all gateway database secrets after rotating SECRET_KEY. Covers encrypted model fields, Authenticator config, and Preferences."

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

        if not dry_run and not use_custom_key:
            self.stdout.write(self.new_key)

    # ── encrypted_fields on AbstractCommonModel subclasses ───────────────

    def _rotate_encrypted_fields(self, dry_run: bool) -> int:
        total = 0
        for model, field_names in _iter_models_with_encrypted_fields():
            for field_name in field_names:
                try:
                    field_obj = model._meta.get_field(field_name)
                except Exception:
                    logger.warning("Model %s declares encrypted field %r but has no such DB column", model.__name__, field_name)
                    continue
                total += self._reencrypt_column(model, field_obj.column, dry_run)
        return total

    # ── Authenticator.configuration encrypted sub-fields ─────────────────

    def _rotate_authenticator_configs(self, dry_run: bool) -> int:
        total = 0
        select_sql = self._build_authenticator_select_sql()
        update_sql = self._build_authenticator_update_sql()

        with connection.cursor() as cur:
            cur.execute(select_sql)
            while True:
                rows = cur.fetchmany(_FETCH_BATCH_SIZE)
                if not rows:
                    break
                for pk, auth_type, config in rows:
                    if not config or not isinstance(config, dict):
                        continue
                    try:
                        plugin = get_authenticator_plugin(auth_type)
                    except ImportError:
                        logger.warning("Cannot load plugin %r for Authenticator pk=%s; skipping", auth_type, pk)
                        continue
                    encrypted_fields = getattr(plugin, 'configuration_encrypted_fields', [])
                    changed = False
                    for field in encrypted_fields:
                        val = config.get(field)
                        if not val or not isinstance(val, str) or ENCRYPTED_STRING not in val:
                            continue
                        try:
                            clear = decrypt_with_key(val, self.old_key)
                        except Exception:
                            logger.warning("Cannot decrypt Authenticator pk=%s field %r with the current SECRET_KEY; skipping", pk, field)
                            continue
                        config[field] = encrypt_with_key(clear, self.new_key)
                        changed = True
                        total += 1
                    if changed and not dry_run:
                        with connection.cursor() as ucur:
                            ucur.execute(update_sql, [json.dumps(config), pk])
        return total

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

        Safe from SQL injection: all identifiers originate from Django
        model metadata and are quoted via the database backend.
        """
        qn = connection.ops.quote_name
        return "UPDATE {table} SET {config} = %s WHERE {pk} = %s".format(
            table=qn(Authenticator._meta.db_table),
            config=qn(Authenticator._meta.get_field('configuration').column),
            pk=qn(Authenticator._meta.pk.column),
        )

    # ── Preference rows (encrypted=True) ─────────────────────────────────

    def _rotate_preferences(self, dry_run: bool) -> int:
        from aap_gateway_api.models import Preference

        select_sql = self._build_preference_select_sql(Preference)
        update_sql = self._build_preference_update_sql(Preference)
        count = 0
        last_pk = None

        while True:
            with connection.cursor() as cur:
                if last_pk is None:
                    cur.execute(select_sql.format(pk_clause=""))
                else:
                    cur.execute(select_sql.format(pk_clause="AND {pk} > %s ".format(pk=connection.ops.quote_name(Preference._meta.pk.column))), [last_pk])
                rows = cur.fetchall()
            if not rows:
                break
            last_pk = rows[-1][0]
            for pk, raw in rows:
                if not raw or ENCRYPTED_STRING not in str(raw):
                    continue
                try:
                    clear = decrypt_with_key(raw, self.old_key)
                except Exception:
                    logger.warning("Cannot decrypt Preference pk=%s with the current SECRET_KEY; skipping", pk)
                    continue
                new_val = encrypt_with_key(clear, self.new_key)
                if not dry_run:
                    with connection.cursor() as ucur:
                        ucur.execute(update_sql, [new_val, pk])
                count += 1
        return count

    @staticmethod
    def _build_preference_select_sql(model) -> str:
        """Build paginated SELECT for preference scanning.

        Returns a format string with a ``{pk_clause}`` placeholder that
        is filled in at call time (empty for the first page, ``AND pk > %s``
        for subsequent pages).

        Safe from SQL injection: all identifiers originate from Django
        model metadata and are quoted via the database backend.
        """
        qn = connection.ops.quote_name
        return ("SELECT {pk}, {val} FROM {table} WHERE {val} IS NOT NULL {{pk_clause}}ORDER BY {pk} LIMIT {limit}").format(
            pk=qn(model._meta.pk.column),
            val=qn('raw_value'),
            table=qn(model._meta.db_table),
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

    # ── Shared column re-encryption ──────────────────────────────────────

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
    def _build_column_update_sql(model, column_name) -> str:
        """Build an UPDATE query for re-encrypting a single row.

        Safe from SQL injection: all identifiers originate from Django
        model metadata and are quoted via the database backend.
        """
        qn = connection.ops.quote_name
        return "UPDATE {table} SET {col} = %s WHERE {pk} = %s".format(
            table=qn(model._meta.db_table),
            col=qn(column_name),
            pk=qn(model._meta.pk.column),
        )

    def _reencrypt_column(self, model, column_name: str, dry_run: bool) -> int:
        first_page_sql = self._build_column_select_sql(model, column_name, with_pk_bound=False)
        next_page_sql = self._build_column_select_sql(model, column_name, with_pk_bound=True)
        update_sql = self._build_column_update_sql(model, column_name)
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
                if not raw or ENCRYPTED_STRING not in str(raw):
                    continue
                try:
                    clear = decrypt_with_key(raw, self.old_key)
                except Exception:
                    logger.warning("Cannot decrypt %s.%s pk=%s with the current SECRET_KEY; skipping", model.__name__, column_name, pk)
                    continue
                new_val = encrypt_with_key(clear, self.new_key)
                if not dry_run:
                    with connection.cursor() as ucur:
                        ucur.execute(update_sql, [new_val, pk])
                count += 1
        return count
