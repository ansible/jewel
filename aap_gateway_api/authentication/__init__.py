from drf_spectacular.extensions import OpenApiAuthenticationExtension


class LoggedOAuth2AuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = 'ansible_base.oauth2_provider.authentication.LoggedOAuth2Authentication'
    name = 'OAuth2_Authentication'

    def get_security_definition(self, auto_schema):
        return {'type': 'apiKey', 'in': 'header', 'name': 'Authorization', 'description': 'Token-based authentication with format "Bearer &lt;base64token&gt;"'}
