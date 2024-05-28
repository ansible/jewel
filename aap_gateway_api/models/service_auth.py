import secrets

from ansible_base.lib.abstract_models.common import CommonModel
from ansible_base.lib.utils.models import prevent_search
from django.conf import settings
from django.db import models
from django.utils.translation import gettext as _
from rest_framework.serializers import ValidationError


class ServiceKeyManager(models.Manager):
    def create(self, **obj_data):
        secret_length = 64
        if "secret_length" in obj_data:
            secret_length = obj_data.pop("secret_length")

        obj_data["secret"] = secrets.token_urlsafe(secret_length)
        return super().create(**obj_data)


class ServiceKey(CommonModel):
    objects = ServiceKeyManager()
    encrypted_fields = ["secret"]

    def save(self, *args, **kwargs):
        max_active = settings.MAX_ACTIVE_KEYS_PER_SERVICE

        if self.is_active and ServiceKey.objects.filter(service_cluster=self.service_cluster, is_active=True).count() - 1 >= max_active:
            raise ValidationError({"is_active": _(f"Cannot have more than {max_active} active keys per service.")})

        return super().save(*args, **kwargs)

    class JWTAlgorithm(models.TextChoices):
        HS256 = "HS256", "HMAC with SHA256"
        HS384 = "HS384", "HMAC with SHA384"
        HS512 = "HS512", "HMAC with SHA512"

    algorithm = models.CharField(
        max_length=10,
        choices=JWTAlgorithm.choices,
        default=JWTAlgorithm.HS256,
    )

    secret = prevent_search(models.TextField(editable=False))
    service_cluster = models.ForeignKey(
        "ServiceCluster",
        on_delete=models.CASCADE,
        related_name="service_keys",
    )
    is_active = models.BooleanField(default=True, null=False)
