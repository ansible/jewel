from ..module_utils.aap_object import AAPObject


class AAPAuthenticator(AAPObject):
    API_ENDPOINT_NAME = "authenticators"
    ITEM_TYPE = "authenticator"

    def unique_field(self):
        return self.module.IDENTITY_FIELDS['http_ports']

    def set_new_fields(self):
        # Create the data that gets sent for create and update
        self.set_name_field()

        if (slug := self.module.params.get('slug')) is not None:
            self.new_fields['slug'] = slug

        if (enabled := self.module.params.get('enabled')) is not None:
            self.new_fields['enabled'] = enabled

        if (create_objects := self.module.params.get('create_objects')) is not None:
            self.new_fields['create_objects'] = create_objects

        if (remove_users := self.module.params.get('remove_users')) is not None:
            self.new_fields['remove_users'] = remove_users

        if (configuration := self.module.params.get('configuration')) is not None:
            self.new_fields['configuration'] = configuration

        if (type := self.module.params.get('type')) is not None:
            self.new_fields['type'] = type

        if (order := self.module.params.get('order')) is not None:
            self.new_fields['order'] = order
