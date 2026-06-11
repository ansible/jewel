"""Tests for _diagnose_key in jwt_token.py.

These tests do not require Django or database access — _diagnose_key is a
pure diagnostic function that only logs.
"""

import logging

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from aap_gateway_api.utils.jwt_token import _diagnose_key


def _generate_rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def _generate_ec_keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


class TestDiagnoseKeyEmpty:
    """Key material is empty or None."""

    @pytest.mark.parametrize("key_material", [None, "", b""])
    def test_empty_public_key(self, key_material, caplog):
        with caplog.at_level(logging.ERROR):
            _diagnose_key(key_material, public=True)
        assert "JWT public key is empty or None" in caplog.text

    @pytest.mark.parametrize("key_material", [None, "", b""])
    def test_empty_private_key(self, key_material, caplog):
        with caplog.at_level(logging.ERROR):
            _diagnose_key(key_material, public=False)
        assert "JWT private key is empty or None" in caplog.text


class TestDiagnoseKeyWrongType:
    """Key material is not a string or bytes."""

    @pytest.mark.parametrize("key_material", [42, 3.14, ["a", "list"], {"a": "dict"}])
    def test_wrong_type_public(self, key_material, caplog):
        with caplog.at_level(logging.ERROR):
            _diagnose_key(key_material, public=True)
        assert "JWT public key is not a string" in caplog.text
        assert type(key_material).__name__ in caplog.text

    @pytest.mark.parametrize("key_material", [42, 3.14, ["a", "list"], {"a": "dict"}])
    def test_wrong_type_private(self, key_material, caplog):
        with caplog.at_level(logging.ERROR):
            _diagnose_key(key_material, public=False)
        assert "JWT private key is not a string" in caplog.text
        assert type(key_material).__name__ in caplog.text


class TestDiagnoseKeyCryptographyRejects:
    """Key material that cryptography cannot parse."""

    def test_garbage_public_key(self, caplog):
        with caplog.at_level(logging.ERROR):
            _diagnose_key("not-a-pem-key", public=True)
        assert "JWT public key failed cryptography validation" in caplog.text

    def test_garbage_private_key(self, caplog):
        with caplog.at_level(logging.ERROR):
            _diagnose_key("not-a-pem-key", public=False)
        assert "JWT private key failed cryptography validation" in caplog.text

    def test_corrupted_pem_public_key(self, caplog):
        _, public_pem = _generate_rsa_keypair()
        corrupted = public_pem.replace("A", "z").replace("B", "x")
        with caplog.at_level(logging.ERROR):
            _diagnose_key(corrupted, public=True)
        assert "JWT public key failed cryptography validation" in caplog.text

    def test_corrupted_pem_private_key(self, caplog):
        private_pem, _ = _generate_rsa_keypair()
        corrupted = private_pem.replace("A", "z").replace("B", "x")
        with caplog.at_level(logging.ERROR):
            _diagnose_key(corrupted, public=False)
        assert "JWT private key failed cryptography validation" in caplog.text

    def test_bytes_input(self, caplog):
        with caplog.at_level(logging.ERROR):
            _diagnose_key(b"not-a-pem-key", public=True)
        assert "JWT public key failed cryptography validation" in caplog.text


class TestDiagnoseKeyCryptographyPassesPyJWTRejects:
    """Key that cryptography accepts but PyJWT rejects (e.g., EC key for RS256)."""

    def test_ec_public_key_rejected_by_pyjwt(self, caplog):
        _, ec_public_pem = _generate_ec_keypair()
        with caplog.at_level(logging.ERROR):
            _diagnose_key(ec_public_pem, public=True)
        assert "passes cryptography validation but PyJWT rejects it" in caplog.text

    def test_ec_private_key_rejected_by_pyjwt(self, caplog):
        ec_private_pem, _ = _generate_ec_keypair()
        with caplog.at_level(logging.ERROR):
            _diagnose_key(ec_private_pem, public=False)
        assert "passes cryptography validation but PyJWT rejects it" in caplog.text


class TestDiagnoseKeyBothPass:
    """Valid RSA key that both cryptography and PyJWT accept."""

    def test_valid_rsa_public_key(self, caplog):
        _, public_pem = _generate_rsa_keypair()
        with caplog.at_level(logging.ERROR):
            _diagnose_key(public_pem, public=True)
        assert "passes both cryptography and PyJWT prepare_key validation" in caplog.text

    def test_valid_rsa_private_key(self, caplog):
        private_pem, _ = _generate_rsa_keypair()
        with caplog.at_level(logging.ERROR):
            _diagnose_key(private_pem, public=False)
        assert "passes both cryptography and PyJWT prepare_key validation" in caplog.text
