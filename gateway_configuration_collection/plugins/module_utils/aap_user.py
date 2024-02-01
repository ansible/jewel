from ..module_utils.aap_object import AAPObject  # noqa


class AAPUser(AAPObject):
    API_ENDPOINT_NAME = "users"
    ITEM_NAME = "user"

    def unique_field(self):
        return self.module.IDENTITY_FIELDS['users']

    def set_new_fields(self):
        # Create the data that gets sent for create and update
        if (username := self.module.params.get("username")) is not None:
            self.new_fields["username"] = self.module.get_item_name(self.data) if self.data else username
        if (first_name := self.module.params.get("first_name")) is not None:
            self.new_fields["first_name"] = first_name
        if (last_name := self.module.params.get("last_name")) is not None:
            self.new_fields["last_name"] = last_name
        if (email := self.module.params.get("email")) is not None:
            self.new_fields["email"] = email
        if (is_superuser := self.module.params.get("is_superuser")) is not None:
            self.new_fields["is_superuser"] = is_superuser
        if (is_system_auditor := self.module.params.get("is_system_auditor")) is not None:
            self.new_fields["is_system_auditor"] = is_system_auditor
        if (password := self.module.params.get("password")) is not None:
            self.new_fields["password"] = password
        if (organizations := self.module.params.get("organizations")) is not None:
            self.new_fields["organizations"] = organizations
