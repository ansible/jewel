# import pytest
# from aap.gateway.auth import GatewayCommonAuth
# from django.test.utils import override_settings

# class TestGatewayCommonAuth:
#    @pytest.mark.django_db
#    @override_settings(INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes'])
#    def test_parse_jwt(self, mocked_http, test_encryption_public_key):
#        with override_settings(AAP_GATEWAY_KEY=test_encryption_public_key):
#            my_auth = GatewayCommonAuth()
#            user, validated_body = my_auth.parse_jwt_token(mocked_http.mocked_parse_jwt_token_get_request('with_headers'))
#            print(user)
#            print(validated_body)


# TODO: Either create a dummy django app we wait to test this with OR make AAP-Gateway a client to itself and test with that.
