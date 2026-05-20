"""Encryption helpers that accept explicit key material.

These mirror the behaviour of ``ansible_base.lib.utils.encryption.Fernet256``
but allow the caller to supply a specific key rather than always reading
``settings.SECRET_KEY``.  This is needed for secret-key rotation where
we must decrypt with the old key and re-encrypt with the new key in the
same process.

The ciphertext format is fully compatible with DAB's format
(``$encrypted$UTF8$AESCBC$<base64>``).
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from django.utils.encoding import smart_bytes, smart_str

ENCRYPTED_MARKER = '$encrypted$'
ENCRYPTION_METHOD = 'AESCBC'


class _Fernet256(Fernet):
    """AES-256-CBC Fernet variant keyed from explicit material."""

    def __init__(self, key_material: str):
        h = hashlib.sha512()
        h.update(smart_bytes(key_material))
        key = h.digest()
        self._signing_key = key[:32]
        self._encryption_key = key[32:]
        self._backend = default_backend()


def encrypt_with_key(value: Any, key_material: str) -> str:
    """Encrypt *value* using *key_material*, producing DAB-compatible ciphertext."""
    f = _Fernet256(key_material)
    payload = json.dumps(value)
    encrypted = f.encrypt(smart_bytes(payload))
    b64data = smart_str(base64.b64encode(encrypted))
    return f'{ENCRYPTED_MARKER}UTF8${ENCRYPTION_METHOD}${b64data}'


def decrypt_with_key(value: str, key_material: str) -> Any:
    """Decrypt DAB-format ciphertext using *key_material*."""
    if not value.startswith(ENCRYPTED_MARKER):
        raise ValueError(f'Value does not start with {ENCRYPTED_MARKER!r}')
    raw = value[len(ENCRYPTED_MARKER) :]
    if raw.startswith('UTF8$'):
        raw = raw[len('UTF8$') :]
    algo, b64data = raw.split('$', 1)
    if algo != ENCRYPTION_METHOD:
        raise ValueError(f'Unsupported algorithm: {algo}')
    encrypted = base64.b64decode(b64data)
    f = _Fernet256(key_material)
    decrypted = smart_str(f.decrypt(encrypted))
    return json.loads(decrypted)
