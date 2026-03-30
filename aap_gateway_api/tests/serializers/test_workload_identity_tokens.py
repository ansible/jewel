import pytest

from aap_gateway_api.serializers.workload_identity_tokens import (
    WORKLOAD_TTL_MAX_SECONDS,
    WorkloadIdentityTokenRequestSerializer,
    WorkloadIdentityTokenResponseSerializer,
)


class TestWorkloadIdentityTokenRequestSerializer:
    """
    Test suite for WorkloadIdentityTokenRequestSerializer.
    """

    def test_valid_data(self):
        valid_data = {
            'scope': 'openid profile',
            'audience': 'https://api.example.com',
            'claims': {
                'job_name': 'deploy-production',
                'organization_name': 'LaPaloma',
                'project_name': 'web-app',
                'job_template_name': 'deploy-template',
            },
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=valid_data)
        assert serializer.is_valid(), f"Serializer errors: {serializer.errors}"
        assert serializer.validated_data == valid_data

    @pytest.mark.parametrize("missing_field", ["scope", "audience", "claims"])
    def test_missing_required_field(self, missing_field):
        data = {
            'scope': 'openid',
            'audience': 'https://api.example.com',
            'claims': {'job_name': 'test-job'},
        }
        del data[missing_field]
        serializer = WorkloadIdentityTokenRequestSerializer(data=data)
        assert not serializer.is_valid()
        assert missing_field in serializer.errors
        assert serializer.errors[missing_field][0].code == 'required'

    @pytest.mark.parametrize(
        "field, value, expected_code",
        [
            pytest.param("scope", None, "null", id="null_scope"),
            pytest.param("audience", None, "null", id="null_audience"),
            pytest.param("scope", "", "blank", id="blank_scope"),
            pytest.param("audience", "", "blank", id="blank_audience"),
            pytest.param("claims", None, "null", id="null_claims"),
        ],
    )
    def test_invalid_field_values(self, field, value, expected_code):
        data = {
            'scope': 'openid',
            'audience': 'https://api.example.com',
            'claims': {'job_name': 'test-job'},
        }
        data[field] = value
        serializer = WorkloadIdentityTokenRequestSerializer(data=data)
        assert not serializer.is_valid()
        assert field in serializer.errors
        assert serializer.errors[field][0].code == expected_code

    def test_empty_claims(self):
        invalid_data = {
            'scope': 'openid',
            'audience': 'https://api.example.com',
            'claims': {},
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=invalid_data)
        assert not serializer.is_valid()
        assert 'claims' in serializer.errors
        assert serializer.errors['claims'][0].code == 'empty'

    def test_claims_not_dict(self):
        invalid_data = {
            'scope': 'openid',
            'audience': 'https://api.example.com',
            'claims': 'not-a-dict',
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=invalid_data)
        assert not serializer.is_valid()
        assert 'claims' in serializer.errors
        assert serializer.errors['claims'][0].code == 'not_a_dict'

    def test_nested_claims(self):
        valid_data = {
            'scope': 'openid',
            'audience': 'https://api.example.com',
            'claims': {
                'job_name': 'deploy-prod',
                'organization_name': 'LaPaloma',
                'metadata': {
                    'created_by': 'user@example.com',
                    'tags': ['production', 'critical'],
                },
            },
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=valid_data)
        assert serializer.is_valid(), f"Serializer errors: {serializer.errors}"
        assert serializer.validated_data == valid_data

    def test_multiple_scopes(self):
        valid_data = {
            'scope': 'openid profile email',
            'audience': 'https://api.example.com',
            'claims': {'job_name': 'test-job'},
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=valid_data)
        assert serializer.is_valid(), f"Serializer errors: {serializer.errors}"

    def test_extra_fields_ignored(self):
        data_with_extra = {
            'scope': 'openid',
            'audience': 'https://api.example.com',
            'claims': {'job_name': 'test-job'},
            'extra_field': 'should be ignored',
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=data_with_extra)
        assert serializer.is_valid(), f"Serializer errors: {serializer.errors}"
        assert 'extra_field' not in serializer.validated_data

    def test_workload_ttl_seconds_valid_value(self):
        valid_data = {
            'scope': 'openid',
            'audience': 'https://api.example.com',
            'claims': {'job_name': 'test-job'},
            'workload_ttl_seconds': 7200,
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=valid_data)
        assert serializer.is_valid(), f"Serializer errors: {serializer.errors}"
        assert serializer.validated_data['workload_ttl_seconds'] == 7200

    @pytest.mark.parametrize(
        "ttl_value, expected_error_code",
        [
            pytest.param(0, 'min_value', id="zero"),
            pytest.param(-100, 'min_value', id="negative"),
            pytest.param(WORKLOAD_TTL_MAX_SECONDS + 1, 'max_value', id="exceeds_max"),
            pytest.param('not-a-number', 'invalid', id="string"),
            pytest.param(3.14, 'invalid', id="float"),
        ],
    )
    def test_workload_ttl_seconds_invalid_values(self, ttl_value, expected_error_code):
        invalid_data = {
            'scope': 'openid',
            'audience': 'https://api.example.com',
            'claims': {'job_name': 'test-job'},
            'workload_ttl_seconds': ttl_value,
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=invalid_data)
        assert not serializer.is_valid()
        assert 'workload_ttl_seconds' in serializer.errors
        assert serializer.errors['workload_ttl_seconds'][0].code == expected_error_code

    def test_workload_ttl_seconds_null(self):
        valid_data = {
            'scope': 'openid',
            'audience': 'https://api.example.com',
            'claims': {'job_name': 'test-job'},
            'workload_ttl_seconds': None,
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=valid_data)
        assert serializer.is_valid(), f"Serializer errors: {serializer.errors}"
        assert serializer.validated_data['workload_ttl_seconds'] is None

    def test_workload_ttl_seconds_omitted(self):
        valid_data = {
            'scope': 'openid',
            'audience': 'https://api.example.com',
            'claims': {'job_name': 'test-job'},
        }
        serializer = WorkloadIdentityTokenRequestSerializer(data=valid_data)
        assert serializer.is_valid(), f"Serializer errors: {serializer.errors}"
        assert 'workload_ttl_seconds' not in serializer.validated_data

    def test_workload_ttl_seconds_max_value_uses_get_setting(self):
        field = WorkloadIdentityTokenRequestSerializer().fields['workload_ttl_seconds']
        assert field.max_value == WORKLOAD_TTL_MAX_SECONDS


class TestWorkloadIdentityTokenResponseSerializer:
    """
    Test suite for WorkloadIdentityTokenResponseSerializer.
    """

    def test_valid_jwt(self):
        valid_data = {
            'jwt': (
                'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.'
                'eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.'
                'SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c'
            ),
        }
        serializer = WorkloadIdentityTokenResponseSerializer(data=valid_data)
        assert serializer.is_valid(), f"Serializer errors: {serializer.errors}"
        assert serializer.validated_data == valid_data

    def test_missing_jwt(self):
        invalid_data = {}
        serializer = WorkloadIdentityTokenResponseSerializer(data=invalid_data)
        assert not serializer.is_valid()
        assert 'jwt' in serializer.errors
        assert serializer.errors['jwt'][0].code == 'required'

    def test_null_jwt(self):
        invalid_data = {'jwt': None}
        serializer = WorkloadIdentityTokenResponseSerializer(data=invalid_data)
        assert not serializer.is_valid()
        assert 'jwt' in serializer.errors
        assert serializer.errors['jwt'][0].code == 'null'

    def test_blank_jwt(self):
        invalid_data = {'jwt': ''}
        serializer = WorkloadIdentityTokenResponseSerializer(data=invalid_data)
        assert not serializer.is_valid()
        assert 'jwt' in serializer.errors
        assert serializer.errors['jwt'][0].code == 'blank'

    def test_jwt_with_whitespace(self):
        data_with_whitespace = {
            'jwt': ('  eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U  '),
        }
        serializer = WorkloadIdentityTokenResponseSerializer(data=data_with_whitespace)
        assert serializer.is_valid(), f"Serializer errors: {serializer.errors}"
        assert serializer.validated_data['jwt'] == data_with_whitespace['jwt'].strip()

    def test_create_response_serializer(self):
        jwt_token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U'
        serializer = WorkloadIdentityTokenResponseSerializer({'jwt': jwt_token})
        assert serializer.data == {'jwt': jwt_token}

    def test_extra_fields_ignored(self):
        data_with_extra = {
            'jwt': ('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U'),
            'extra_field': 'should be ignored',
        }
        serializer = WorkloadIdentityTokenResponseSerializer(data=data_with_extra)
        assert serializer.is_valid(), f"Serializer errors: {serializer.errors}"
        assert 'extra_field' not in serializer.validated_data
