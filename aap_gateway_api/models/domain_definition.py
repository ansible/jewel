from ansible_base.activitystream.models import AuditableModel
from ansible_base.lib.abstract_models.common import CommonModel
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class DomainDefinition(CommonModel, AuditableModel):
    """Domain definitions owned by an organization, team, or user."""

    audit_log_enabled = True

    ORGANIZATION = 'organization'
    TEAM = 'team'
    USER = 'user'
    SCOPE_CHOICES = (
        (ORGANIZATION, _('Organization')),
        (TEAM, _('Team')),
        (USER, _('User')),
    )

    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, help_text=_('The scope that owns this domain definition.'))
    domains = models.JSONField(default=list, help_text=_('The domains configured for this scope.'))
    organization = models.ForeignKey(
        settings.ANSIBLE_BASE_ORGANIZATION_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='domain_definitions',
        help_text=_('The organization that owns this domain definition.'),
    )
    team = models.ForeignKey(
        settings.ANSIBLE_BASE_TEAM_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='domain_definitions',
        help_text=_('The team that owns this domain definition.'),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='domain_definitions',
        help_text=_('The user that owns this domain definition.'),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('organization', 'scope'), name='domain_definition_org_scope_uniq'),
            models.UniqueConstraint(fields=('team', 'scope'), name='domain_definition_team_scope_uniq'),
            models.UniqueConstraint(fields=('user', 'scope'), name='domain_definition_user_scope_uniq'),
            models.CheckConstraint(
                condition=(
                    (Q(scope='organization') & Q(organization__isnull=False) & Q(team__isnull=True) & Q(user__isnull=True))
                    | (Q(scope='team') & Q(organization__isnull=True) & Q(team__isnull=False) & Q(user__isnull=True))
                    | (Q(scope='user') & Q(organization__isnull=True) & Q(team__isnull=True) & Q(user__isnull=False))
                ),
                name='domain_definition_one_owner_scope',
            ),
        ]
