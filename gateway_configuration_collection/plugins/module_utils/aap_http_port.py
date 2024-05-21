from ..module_utils.aap_object import AAPObject

__metaclass__ = type


class AAPHttpPort(AAPObject):
    API_ENDPOINT_NAME = "http_ports"
    ITEM_TYPE = "http_port"

    def unique_field(self):
        return self.module.IDENTITY_FIELDS['http_ports']

    def set_new_fields(self):
        # Create the data that gets sent for create and update
        self.set_name_field()

        if (number := self.module.params.get('number')) is not None:
            self.new_fields['number'] = number

        if (use_https := self.module.params.get('use_https')) is not None:
            self.new_fields['use_https'] = use_https

        if (is_api_port := self.module.params.get('is_api_port')) is not None:
            self.new_fields['is_api_port'] = is_api_port
