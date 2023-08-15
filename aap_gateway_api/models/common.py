import logging

from crum import get_current_user
from django.db import models
from django.utils.timezone import now
from rest_framework.reverse import reverse_lazy

from aap_gateway_api.models.user import User

logger = logging.getLogger('aap.gateway.models.common')


class CommonModel(models.Model):
    class Meta:
        abstract = True

    created_on = models.DateTimeField(
        default=None,
        editable=False,
    )
    created_by = models.ForeignKey(
        User,
        related_name='%(app_label)s_%(class)s_created+',
        default=None,
        null=True,
        editable=False,
        on_delete=models.DO_NOTHING,
    )
    modified_on = models.DateTimeField(
        default=None,
        editable=False,
    )
    modified_by = models.ForeignKey(
        User,
        related_name='%(app_label)s_%(class)s_modified+',
        default=None,
        null=True,
        editable=False,
        on_delete=models.DO_NOTHING,
    )

    def save(self, *args, **kwargs):
        update_fields = list(kwargs.get('update_fields', []))
        user = get_current_user()
        # Manually perform auto_now_add and auto_now logic.
        if not self.pk and not self.created_on:
            self.created_on = now()
            self.created_by = user
            if 'created_on' not in update_fields:
                update_fields.append('created_on')
            if 'created_by' not in update_fields:
                update_fields.append('created_by')
        if 'modified_on' not in update_fields or not self.modified_on:
            self.modified_on = now()
            self.modified_by = user
            update_fields.append('modified_on')
            update_fields.append('modified_by')
        super().save(*args, **kwargs)

    def related_fields(self, request):
        response = {}
        if self.created_by:
            response['created_by'] = reverse_lazy('user-detail', kwargs={'pk': self.created_by.pk}, request=request)
        if self.modified_by:
            response['modified_by'] = reverse_lazy('user-detail', kwargs={'pk': self.modified_by.pk}, request=request)
        return response

    def summary_fields(self):
        response = {}
        response['id'] = self.id
        return response


class NamedCommonModel(CommonModel):
    class Meta:
        abstract = True

    name = models.CharField(
        max_length=512,
        unique=True,
    )

    def summary_fields(self):
        res = super().summary_fields()
        res['name'] = self.name
        return res
