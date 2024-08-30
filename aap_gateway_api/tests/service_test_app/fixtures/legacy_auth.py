import os

from service_test_app.models import User
from social_django.models import UserSocialAuth

from .data.legacy_auth import USERS


def setup():
    service_type = os.environ.get("SERVICE_TEST_APP_TYPE", "aap")

    for username in USERS:
        if user := USERS[username].get(service_type, None):
            u = User.objects.create(username=username)
            if user.backend:
                social_auth_kwargs = {
                    "uid": user.get_uid(),
                    "provider": user.backend.backend,
                    "user": u,
                    "extra_data": user.get_extra_data(),
                }

                UserSocialAuth.objects.create(**social_auth_kwargs)
            if password := user.password:
                u.set_password(password)
                u.save()
