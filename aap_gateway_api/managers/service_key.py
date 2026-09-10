import secrets

from django.db import models


class ServiceKeyManager(models.Manager):
    def create(self, **obj_data):
        secret_length = 64
        if "secret_length" in obj_data:
            secret_length = obj_data.pop("secret_length")

        obj_data["secret"] = secrets.token_urlsafe(secret_length)
        return super().create(**obj_data)
