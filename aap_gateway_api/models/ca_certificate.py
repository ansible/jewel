from ansible_base.activitystream.models import AuditableModel
from ansible_base.lib.abstract_models.common import UniqueNamedCommonModel
from django.db import models
from django.utils.translation import gettext as _


class CACertificate(UniqueNamedCommonModel, AuditableModel):
    """
    Individual CA Certificate, used to validate the customers
    incoming requests. The data can include a chain of
    certificate in PEM format.
    """

    router_basename = 'ca_certificates'

    pem_data = models.TextField(help_text=_("Certificate content in PEM format"), null=False)
    # The SHA 256 can be used by the caller to detect if there are updates to the certificate
    # This is used by the callers since they control how the SHA256 is computed
    # If we computed this on the server side the line endings \r\n or \n might lead
    # to different results.
    sha256 = models.CharField(help_text=_("SHA256 signature of pem_data"), max_length=64)
    related_id_reference = models.CharField(help_text=_("Reference to an object that is related to this CA."), max_length=64, blank=True)
