from ..module_utils.aap_object import AAPObject

__metaclass__ = type


class AAPServiceCluster(AAPObject):
    API_ENDPOINT_NAME = "service_clusters"
    ITEM_TYPE = "service_cluster"

    def unique_field(self):
        return self.module.IDENTITY_FIELDS['service_clusters']

    def set_new_fields(self):
        # Create the data that gets sent for create and update
        self.set_name_field()

        if (service_type := self.params.get('service_type')) is not None:
            self.new_fields["service_type"] = service_type
