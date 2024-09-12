from django.contrib.auth.backends import ModelBackend


class LDAPBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if 'ldap' not in username:
            return None
        return super().authenticate(request, username, password, **kwargs)


class RadiusBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if 'radius' not in username:
            return None
        return super().authenticate(request, username, password, **kwargs)
