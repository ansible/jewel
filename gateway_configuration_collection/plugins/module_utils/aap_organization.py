from ..module_utils.aap_object import AAPObject


class AAPOrganization(AAPObject):
    API_ENDPOINT_NAME = "organizations"
    ITEM_TYPE = "organization"

    def unique_field(self):
        return self.module.IDENTITY_FIELDS['organizations']

    def set_new_fields(self):
        # Create the data that gets sent for create and update
        self.set_name_field()

        if (description := self.params.get('description')) is not None:
            self.new_fields['description'] = description

        if (users := self.params.get('users')) is not None:
            self.new_fields['users'] = users

        if (admins := self.params.get('admins')) is not None:
            self.new_fields['admins'] = admins
