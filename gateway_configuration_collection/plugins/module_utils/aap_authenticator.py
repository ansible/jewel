from __future__ import absolute_import, division, print_function

__metaclass__ = type

from ..module_utils.aap_object import AAPObject


class AAPAuthenticator(AAPObject):
    API_ENDPOINT_NAME = "authenticators"
    ITEM_TYPE = "authenticator"

    def unique_field(self):
        return self.module.IDENTITY_FIELDS['http_ports']

    def set_new_fields(self):
        # Create the data that gets sent for create and update
        self.set_name_field()

        slug = self.module.params.get('slug')
        if slug is not None:
            self.new_fields['slug'] = slug

        enabled = self.module.params.get('enabled')
        if enabled is not None:
            self.new_fields['enabled'] = enabled

        create_objects = self.module.params.get('create_objects')
        if create_objects is not None:
            self.new_fields['create_objects'] = create_objects

        remove_users = self.module.params.get('remove_users')
        if remove_users is not None:
            self.new_fields['remove_users'] = remove_users

        configuration = self.module.params.get('configuration')
        if configuration is not None:
            self.new_fields['configuration'] = configuration

        _type = self.module.params.get('type')
        if _type is not None:
            self.new_fields['type'] = _type

        order = self.module.params.get('order')
        if order is not None:
            self.new_fields['order'] = order
