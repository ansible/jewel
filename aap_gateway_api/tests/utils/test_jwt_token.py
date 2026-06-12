import logging
from datetime import datetime, timedelta
from functools import partial
from unittest import mock

import jwt as pyjwt
import pytest
from ansible_base.rbac.models import RoleDefinition
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from django.contrib.contenttypes.models import ContentType

from aap_gateway_api.models import Organization, Team, User
from aap_gateway_api.utils.jwt_token import _diagnose_key, create_signed_jwt, decode_signed_jwt, get_jwt_rsa_key, get_user_object_roles, update_jwt_public_key


def _generate_rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
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
        format=serialization.PrivateFormat.PKCS8,
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


def test_jwt_token_org_ends_up_in_jwt_if_only_team_associated(admin_user, team, preference_manager, rsa_keypair):
    RoleDefinition.objects.managed.team_admin.give_permission(admin_user, team)
    # Use preference_manager for JWT keys with proper cleanup
    with preference_manager.set_multiple(
        {
            ("proxy", "jwt_private_key"): rsa_keypair.private,
            ("proxy", "jwt_public_key"): rsa_keypair.public,
        }
    ):
        jwt_token = create_signed_jwt(admin_user)
        decoded = decode_signed_jwt(jwt_token)
        assert decoded['sub'] == str(admin_user.resource.ansible_id)
        assert decoded['service_id'] == str(admin_user.resource.service_id)
        # Check that claims_hash is present and is a valid SHA-256 hash
        assert 'claims_hash' in decoded
        assert isinstance(decoded['claims_hash'], str)
        assert len(decoded['claims_hash']) == 64
        assert all(c in '0123456789abcdef' for c in decoded['claims_hash'])


def test_jwt_token_encode_decode(admin_user, preference_manager, rsa_keypair, organization, team):
    # Give admin is_systemadmin
    admin_user.apply_platform_auditor_membership(True)
    # Give admin a member object permission
    RoleDefinition.objects.managed.org_member.give_permission(admin_user, organization)
    # Give admin an admin object permission
    RoleDefinition.objects.managed.team_admin.give_permission(admin_user, team)

    with preference_manager.set_multiple(
        {
            ("proxy", "jwt_private_key"): rsa_keypair.private,
            ("proxy", "jwt_public_key"): rsa_keypair.public,
        }
    ):
        jwt_token = create_signed_jwt(admin_user)
        decoded = decode_signed_jwt(jwt_token)
        assert decoded["sub"] == str(admin_user.resource.ansible_id)
        assert decoded['user_data']["email"] == admin_user.email
        assert decoded["iss"] == "ansible-issuer"
        assert decoded["aud"] == "ansible-services"

        # Check that claims_hash is present and is a valid SHA-256 hash
        assert 'claims_hash' in decoded
        assert isinstance(decoded['claims_hash'], str)
        assert len(decoded['claims_hash']) == 64
        assert all(c in '0123456789abcdef' for c in decoded['claims_hash'])


def test_jwt_token_update_jwt_public_key_private_key_exception(expected_log):
    expected_log = partial(expected_log, "aap_gateway_api.utils.jwt_token.logger")
    with expected_log("exception", "Unable to load private key from JWT key"):
        with pytest.raises(Exception):
            update_jwt_public_key('junk')


def test_jwt_token_update_jwt_public_key_public_key_exception(expected_log, rsa_keypair):
    expected_log = partial(expected_log, "aap_gateway_api.utils.jwt_token.logger")
    with mock.patch('aap_gateway_api.utils.jwt_token.update_preference_value', side_effect=Exception("Failing on purpose")):
        with expected_log("exception", "Unable to export public key from JWT key"):
            with pytest.raises(Exception):
                update_jwt_public_key(rsa_keypair.private)


def test_jwt_token_get_jwt_rsa_key_private(rsa_keypair, preference_manager):
    with preference_manager.set("proxy", "jwt_private_key", rsa_keypair.private):
        assert get_jwt_rsa_key(public=False) == rsa_keypair.private


def test_jwt_token_get_jwt_rsa_key_public(rsa_keypair, preference_manager):
    with preference_manager.set("proxy", "jwt_private_key", rsa_keypair.private):
        assert get_jwt_rsa_key(public=True) == rsa_keypair.public


def test_jwt_token_get_jwt_rsa_key_public_not_set(rsa_keypair, preference_manager):
    with preference_manager.set_multiple(
        {
            ("proxy", "jwt_private_key"): rsa_keypair.private,
            ("proxy", "jwt_public_key"): '',
        }
    ):
        assert get_jwt_rsa_key(public=True) == rsa_keypair.public


@pytest.mark.django_db
class TestUserObjectRoles:
    @property
    def org_ct(self):
        return ContentType.objects.get_for_model(Organization)

    @property
    def team_ct(self):
        return ContentType.objects.get_for_model(Team)

    def test_platform_auditor(self, user):
        RoleDefinition.objects.managed.platform_auditor.give_global_permission(user)
        assert get_user_object_roles(user) == []  # platform auditor is not an object role

    def test_org_admin(self, user, organization):
        RoleDefinition.objects.managed.org_admin.give_permission(user, organization)
        assert get_user_object_roles(user) == [('Organization Admin', str(organization.resource.ansible_id), self.org_ct.id)]

    def test_org_member_team_admin(self, user, organization, team):
        RoleDefinition.objects.managed.org_member.give_permission(user, organization)
        RoleDefinition.objects.managed.team_admin.give_permission(user, team)
        assert set(get_user_object_roles(user)) == {
            ('Organization Member', str(organization.resource.ansible_id), self.org_ct.id),
            ('Team Admin', str(team.resource.ansible_id), self.team_ct.id),
        }

    def test_several_teams_and_orgs(self, user, organization):
        rando = User.objects.create(username='rando')
        expected = set()
        for i in range(5):
            team = Team.objects.create(name=f'team-{i}', organization=organization)
            if i % 3 == 0:
                RoleDefinition.objects.managed.team_admin.give_permission(user, team)
                expected.add(('Team Admin', str(team.resource.ansible_id), self.team_ct.id))
            elif i % 3 == 1:
                RoleDefinition.objects.managed.team_member.give_permission(user, team)
                expected.add(('Team Member', str(team.resource.ansible_id), self.team_ct.id))
                # red herring data
                RoleDefinition.objects.managed.team_admin.give_permission(rando, team)
            else:
                RoleDefinition.objects.managed.team_member.give_permission(rando, team)

        for i in range(5):
            org = Organization.objects.create(name=f'org-{i}')
            if i % 3 == 1:
                RoleDefinition.objects.managed.org_admin.give_permission(user, org)
                expected.add(('Organization Admin', str(org.resource.ansible_id), self.org_ct.id))
            elif i % 3 == 2:
                RoleDefinition.objects.managed.org_member.give_permission(user, org)
                expected.add(('Organization Member', str(org.resource.ansible_id), self.org_ct.id))
                # red herring data
                RoleDefinition.objects.managed.org_member.give_permission(rando, org)
            else:
                RoleDefinition.objects.managed.org_admin.give_permission(rando, org)

        assert len(expected) == 7
        assert set(get_user_object_roles(user)) == expected

    def test_unique_orgs_and_teams(self, user, preference_manager, rsa_keypair, organization):
        """
        Test that JWT token is generated successfully with multiple team permissions.
        Note: The uniqueness of objects is now validated through the claims hash,
        as the objects data is no longer included in the JWT token itself.
        """

        team1 = Team.objects.create(name="Team 1", organization=organization)
        team2 = Team.objects.create(name="Team 2", organization=organization)
        # Give user team member permission to team 1
        RoleDefinition.objects.managed.team_member.give_permission(user, team1)
        # Give user team member and admin permission to team 2
        RoleDefinition.objects.managed.team_member.give_permission(user, team2)
        RoleDefinition.objects.managed.team_admin.give_permission(user, team2)

        with preference_manager.set_multiple(
            {
                ("proxy", "jwt_private_key"): rsa_keypair.private,
                ("proxy", "jwt_public_key"): rsa_keypair.public,
            }
        ):
            jwt_token = create_signed_jwt(user)
            decoded = decode_signed_jwt(jwt_token)

            # Check that claims_hash is present and is a valid SHA-256 hash
            assert 'claims_hash' in decoded
            assert isinstance(decoded['claims_hash'], str)
            assert len(decoded['claims_hash']) == 64


def test_jwt_token_claims_hash_deterministic(user, preference_manager, rsa_keypair, organization, team):
    """Test that the claims hash is deterministic for the same user permissions"""
    RoleDefinition.objects.managed.org_member.give_permission(user, organization)
    RoleDefinition.objects.managed.team_admin.give_permission(user, team)

    with preference_manager.set_multiple(
        {
            ("proxy", "jwt_private_key"): rsa_keypair.private,
            ("proxy", "jwt_public_key"): rsa_keypair.public,
        }
    ):
        # Create two tokens for the same user
        jwt_token1 = create_signed_jwt(user)
        jwt_token2 = create_signed_jwt(user)

        decoded1 = decode_signed_jwt(jwt_token1)
        decoded2 = decode_signed_jwt(jwt_token2)

        # The claims hash should be identical (though exp timestamps will differ)
        assert decoded1['claims_hash'] == decoded2['claims_hash']


def test_jwt_token_claims_hash_changes_with_permissions(user, preference_manager, rsa_keypair, organization):
    """Test that the claims hash changes when user permissions change"""
    with preference_manager.set_multiple(
        {
            ("proxy", "jwt_private_key"): rsa_keypair.private,
            ("proxy", "jwt_public_key"): rsa_keypair.public,
        }
    ):
        # Create token with no permissions
        jwt_token1 = create_signed_jwt(user)
        decoded1 = decode_signed_jwt(jwt_token1)

        # Add a permission
        RoleDefinition.objects.managed.org_member.give_permission(user, organization)

        # Create token with new permission
        jwt_token2 = create_signed_jwt(user)
        decoded2 = decode_signed_jwt(jwt_token2)

        # The claims hash should be different
        assert decoded1['claims_hash'] != decoded2['claims_hash']


def test_jwt_token_with_resource_api_actions(user, preference_manager, rsa_keypair):
    """Test that resource_api_actions are included in the JWT token"""
    with preference_manager.set_multiple(
        {
            ("proxy", "jwt_private_key"): rsa_keypair.private,
            ("proxy", "jwt_public_key"): rsa_keypair.public,
        }
    ):
        resource_api_actions = ['list', 'retrieve', 'create', 'update', 'destroy']
        jwt_token = create_signed_jwt(user, resource_api_actions=resource_api_actions)
        decoded = decode_signed_jwt(jwt_token)

        assert 'resource_api_actions' in decoded
        assert set(decoded['resource_api_actions']) == set(resource_api_actions)  # order-agnostic check for extra safety

        # Claims hash should still be present
        assert 'claims_hash' in decoded
        assert isinstance(decoded['claims_hash'], str)
        assert len(decoded['claims_hash']) == 64


class TestCritHeaderValidation:
    """Tests for CVE-2026-32597: PyJWT must reject tokens with unrecognized
    critical ('crit') header extensions per RFC 7515 §4.1.11.

    These tests verify that the upgraded PyJWT (>= 2.12.0) properly validates
    the 'crit' header parameter at both the library level and through the
    gateway's own decode paths.
    """

    def _build_rs256_token(self, rsa_keypair, extra_headers=None):
        """Build an RS256-signed JWT with optional extra headers."""
        payload = {
            "sub": "test-user",
            "iss": "ansible-issuer",
            "aud": "ansible-services",
            "exp": int((datetime.now() + timedelta(hours=1)).timestamp()),
        }
        return pyjwt.encode(payload, rsa_keypair.private, algorithm="RS256", headers=extra_headers or {})

    def test_crit_with_unknown_extension_rejected(self, rsa_keypair):
        """A token whose 'crit' header lists an unsupported extension MUST be rejected."""
        token = self._build_rs256_token(rsa_keypair, extra_headers={"crit": ["x-custom-ext"], "x-custom-ext": "value"})

        with pytest.raises(pyjwt.exceptions.InvalidTokenError, match="crit"):
            pyjwt.decode(token, rsa_keypair.public, algorithms=["RS256"], audience="ansible-services")

    def test_crit_with_empty_list_rejected(self, rsa_keypair):
        """A token with an empty 'crit' list is malformed and MUST be rejected."""
        token = self._build_rs256_token(rsa_keypair, extra_headers={"crit": []})

        with pytest.raises(pyjwt.exceptions.InvalidTokenError, match="crit"):
            pyjwt.decode(token, rsa_keypair.public, algorithms=["RS256"], audience="ansible-services")

    def test_crit_rejected_through_gateway_decode(self, rsa_keypair, preference_manager):
        """Tokens with 'crit' headers must also be rejected through decode_signed_jwt."""
        with preference_manager.set_multiple(
            {
                ("proxy", "jwt_private_key"): rsa_keypair.private,
                ("proxy", "jwt_public_key"): rsa_keypair.public,
            }
        ):
            token = self._build_rs256_token(rsa_keypair, extra_headers={"crit": ["x-custom-ext"], "x-custom-ext": "value"})

            with pytest.raises(pyjwt.exceptions.InvalidTokenError, match="crit"):
                decode_signed_jwt(token)

    def test_crit_rejected_even_without_signature_verification(self, rsa_keypair):
        """The crit check fires before (or alongside) signature verification,
        so even an unverified decode path must reject unknown critical extensions."""
        token = self._build_rs256_token(rsa_keypair, extra_headers={"crit": ["x-custom-ext"], "x-custom-ext": "value"})

        with pytest.raises(pyjwt.exceptions.InvalidTokenError, match="crit"):
            pyjwt.decode(token, options={"verify_signature": False, "require": ["iss"]})

    def test_normal_token_without_crit_accepted(self, rsa_keypair):
        """Baseline: a well-formed token without 'crit' should decode normally."""
        token = self._build_rs256_token(rsa_keypair)

        decoded = pyjwt.decode(token, rsa_keypair.public, algorithms=["RS256"], audience="ansible-services")
        assert decoded["sub"] == "test-user"
        assert decoded["iss"] == "ansible-issuer"


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


class TestCreateSignedJwtInvalidKey:
    """Verify create_signed_jwt calls _diagnose_key on InvalidKeyError."""

    @mock.patch("aap_gateway_api.utils.jwt_token._diagnose_key")
    @mock.patch("aap_gateway_api.utils.jwt_token.get_jwt_rsa_key", return_value="bad-key")
    @mock.patch("aap_gateway_api.utils.jwt_token.jwt.encode", side_effect=pyjwt.exceptions.InvalidKeyError("test"))
    @mock.patch("aap_gateway_api.utils.jwt_token.get_preference_value", return_value=300)
    @mock.patch("aap_gateway_api.utils.jwt_token.get_user_claims", return_value={})
    @mock.patch("aap_gateway_api.utils.jwt_token.get_user_claims_hashable_form", return_value=())
    @mock.patch("aap_gateway_api.utils.jwt_token.get_claims_hash", return_value="a" * 64)
    def test_diagnose_called_on_encode_failure(self, _hash, _hashable, _claims, _pref, _encode, _get_key, mock_diagnose):
        fake_user = mock.MagicMock()
        fake_user.resource.ansible_id = "test-id"
        fake_user.resource.service_id = "test-service"
        with pytest.raises(pyjwt.exceptions.InvalidKeyError):
            create_signed_jwt(fake_user)
        mock_diagnose.assert_called_once_with("bad-key", public=False)


class TestDecodeSignedJwtInvalidKey:
    """Verify decode_signed_jwt calls _diagnose_key on InvalidKeyError."""

    @mock.patch("aap_gateway_api.utils.jwt_token._diagnose_key")
    @mock.patch("aap_gateway_api.utils.jwt_token.get_jwt_rsa_key", return_value="bad-key")
    @mock.patch("aap_gateway_api.utils.jwt_token.jwt.decode", side_effect=pyjwt.exceptions.InvalidKeyError("test"))
    def test_diagnose_called_on_decode_failure(self, _decode, _get_key, mock_diagnose):
        with pytest.raises(pyjwt.exceptions.InvalidKeyError):
            decode_signed_jwt("fake-token")
        mock_diagnose.assert_called_once_with("bad-key", public=True)
