from ansible_base.activitystream.models import AuditableModel
from ansible_base.lib.abstract_models.common import CommonModel
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserPreference(CommonModel, AuditableModel):
    """A JSON preference owned by one authenticated platform user."""

    audit_log_enabled = True

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='gateway_user_preferences',
        help_text=_('The user who owns this preference.'),
    )
    name = models.CharField(max_length=100, help_text=_('The preference name.'))
    value = models.JSONField(default=dict, help_text=_('The JSON preference value.'))

    class Meta:
        constraints = [models.UniqueConstraint(fields=('user', 'name'), name='user_preference_user_name_uniq')]
