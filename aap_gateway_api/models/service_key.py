from ansible_base.lib.abstract_models.common import UniqueNamedCommonModel
from ansible_base.lib.utils.models import prevent_search
from django.conf import settings
from django.db import models
from django.utils.translation import gettext as _
from rest_framework.serializers import ValidationError

from aap_gateway_api.managers.service_key import ServiceKeyManager


class ServiceKey(UniqueNamedCommonModel):
    objects = ServiceKeyManager()
    encrypted_fields = ["secret"]
    # We are pulling in name here to allow null=True. These are typically created by a function in Service
    # Allowing for null=True here allows the service to provide a default name if one does not exist
    name = models.CharField(
        max_length=512,
        unique=True,
        null=True,
        help_text=_("The name of this resource."),
    )

    class JWTAlgorithm(models.TextChoices):
        HS256 = "HS256", "HMAC with SHA256"
        HS384 = "HS384", "HMAC with SHA384"
        HS512 = "HS512", "HMAC with SHA512"

    algorithm = models.CharField(
        editable=False,  # If a user changed the algorithm it would effectively disable the key.
        max_length=10,
        choices=JWTAlgorithm.choices,
        default=JWTAlgorithm.HS256,
        help_text=_("The algorithm used to generate the service key."),
    )

    secret = prevent_search(models.TextField(editable=False, help_text=_("The secret will only be plain text on generation, afterwards it will be encrypted.")))

    service_cluster = models.ForeignKey(
        "ServiceCluster",
        editable=False,  # A key should not be allowed to be applied to a difference service cluster.
        on_delete=models.CASCADE,
        related_name="service_keys",
        help_text=_("The service cluster this key is for"),
    )
    is_active = models.BooleanField(default=True, null=False, help_text=_("Is this service key active."))

    def save(self, *args, **kwargs):
        max_active = settings.MAX_ACTIVE_KEYS_PER_SERVICE

        if self.is_active and ServiceKey.objects.filter(service_cluster=self.service_cluster, is_active=True).count() - 1 >= max_active:
            raise ValidationError({"is_active": _(f"Cannot have more than {max_active} active keys per service.")})

        return super().save(*args, **kwargs)
