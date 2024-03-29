import json
import uuid

from aap_gateway_api.utils.resources_client import GWResourceAPIClient

service_id = "109b3a29-17b3-4587-84f2-458232ad5a90"


class MockedResource:
    rtype = None
    list_fields = ["ansible_id", "service_id", "resource_type", "name"]
    detail_fields = ["ansible_id", "service_id", "resource_type", "resource_data", "name"]
    additional_data_fields = []
    name_field = "name"

    def __init__(self, name):
        self.data = {"name": name, "ansible_id": str(uuid.uuid4()), "service_id": service_id, "resource_type": self.rtype}

    def list(self):
        return {x: self.data[x] for x in self.list_fields}

    def detail(self):
        return {x: self.data[x] for x in self.detail_fields}

    def additional_data(self):
        return {**self.data["resource_data"], **self.data.get("additional_data", {})}


class Org(MockedResource):
    rtype = "shared.organization"

    def __init__(self, name):
        super().__init__(name)

        self.data["resource_data"] = {"name": name}


class Team(MockedResource):
    rtype = "shared.team"

    def __init__(self, name, org):
        super().__init__(name)

        self.data["resource_data"] = {"name": name, "organization": org.data["ansible_id"]}


class User(MockedResource):
    rtype = "shared.user"
    name_field = "username"

    def __init__(self, name, **kwargs):
        super().__init__(name)

        memberships = ["teams", "teams_administered", "organizations", "organizations_administered"]

        additional_data = {}
        for k in memberships:
            additional_data[k] = [x.data["ansible_id"] for x in kwargs.get(k, [])]

        self.data["resource_data"] = {"username": name, "email": None, "first_name": None, "last_name": None, "is_superuser": False}

        self.data["additional_data"] = additional_data


class MockResourcesAPI:
    resources = {}

    def add_resource(self, resource):
        self.resources[resource.data["ansible_id"]] = resource
        return resource

    def create_resource(self, data):
        rtypes = {"shared.user": User, "shared.team": Team, "shared.organization": Org}
        klass = rtypes[data["resource_type"]]

        if data["resource_type"] == "shared.team":
            resource = klass(data["resource_data"][klass.name_field], Org(""))
        else:
            resource = klass(data["resource_data"][klass.name_field])

        for k in resource.data.keys():
            if val := data.get(k):
                resource.data[k] = val

        self.add_resource(resource)
        return resource

    def detail(self, ansible_id):
        return self.resources[ansible_id].detail()

    def update(self, ansible_id, data):
        resource = self.resources[ansible_id]

        new_id = data.get("ansible_id", ansible_id)

        if new_id != ansible_id:
            # This is not my finest moment, but it is so much easier than
            # trying to recursively iterate through the whole resources data structure
            for k, v in self.resources.items():
                resources_text = json.dumps(v.data)
                resources_text = resources_text.replace(ansible_id, new_id)
                v.data = json.loads(resources_text)

            self.resources[new_id] = self.resources[ansible_id]
            del self.resources[ansible_id]

        for f in ["ansible_id", "service_id"]:
            if new := data.get(f, None):
                resource.data[f] = new

        if resource_data := data.get("resource_data"):
            for k, v in resource_data.items():
                if k == resource.name_field:
                    resource.data["name"] = v
                resource.data["resource_data"][k] = v

        return self.resources[new_id].detail()

    def delete(self, ansible_id):
        del self.resources[ansible_id]
        return None

    def additional_data(self, ansible_id):
        return self.data[ansible_id].additional_data()

    def list(self, service_id=None, resource_types=None):
        results = []

        for k, v in self.resources.items():
            if service_id and v.data["service_id"] != service_id:
                continue
            if resource_types and v.rtype not in resource_types:
                continue

            results.append(v.list())

        return {"count": len(results), "next": None, "previous": None, "results": results}

    def set_resources(self):
        self.resources = {}
        strickland = self.add_resource(Org("Strickland Propane"))
        tank_wipes = self.add_resource(Team("tank wipes", strickland))
        a_managers = self.add_resource(Team("assistant managers", strickland))
        drivers = self.add_resource(Team("drivers", strickland))

        avengers = self.add_resource((Org("The Avengers")))
        real_h = self.add_resource(Team("Real Super Heroes", avengers))
        normal_h = self.add_resource(Team("Normal people that are just kind of good at stuff", avengers))
        org1 = self.add_resource(Org("Org 1"))
        org2 = self.add_resource(Org("Org 2"))
        org3 = self.add_resource(Org("Org 3"))
        org1_team = self.add_resource(Team("Team 1", org1))
        org2_team = self.add_resource(Team("Team 1", org2))
        org3_team = self.add_resource(Team("Team 1", org3))

        self.add_resource(
            User(
                "hank",
                organizations=[strickland],
                organizations_administered=[strickland],
                teams=[a_managers],
            )
        )
        self.add_resource(
            User(
                "mr_strickland",
                organizations=[strickland],
                organizations_administered=[strickland],
            )
        )
        self.add_resource(
            User(
                "joe_jack",
                organizations=[drivers],
                organizations_administered=[drivers],
            )
        )
        self.add_resource(User("bobby", teams=[tank_wipes]))

        self.add_resource(
            User(
                "t_stark",
                organizations=[avengers],
                organizations_administered=[avengers],
                teams=[normal_h],
                teams_administered=[normal_h],
            )
        )

        self.add_resource(
            User(
                "cpt_murica",
                organizations=[avengers, org1],
                organizations_administered=[org1],
                teams=[real_h],
                teams_administered=[real_h],
            )
        )

        self.add_resource(
            User(
                "point_break",
                teams=[real_h, org1_team, org2_team, org3_team],
            )
        )
        self.add_resource(
            User(
                "natasha",
                teams=[normal_h],
            )
        )
        self.add_resource(
            User(
                "hawk_eye",
                teams=[normal_h],
            )
        )


class Response:
    def __init__(self, data, status=200):
        self.data = data
        self.status_code = status

    def json(self):
        return self.data


MOCKED_API = MockResourcesAPI()


class MockResourceClient(GWResourceAPIClient):
    MOCKED_API = MOCKED_API
    service_id = service_id

    def _make_request(self, method: str, path: str, data: dict = None, params: dict = None):
        # We're using a global method for this so that we can check the state of the
        # resource API after the tests run. This will have to be reset between tests by
        # calling MOCKED_API.set_resources()
        api = self.MOCKED_API
        path = path.strip("/").split("/")
        method = method.lower()

        if "metadata" in path:
            return Response({"service_id": service_id, "service_type": "awx"})
        elif "resources" in path:
            if len(path) == 1:
                if method in ["get"]:
                    if params is None:
                        params = {}

                    data = api.list(service_id=params.get("service_id", None), resource_types=params.get("content_type__resource_type__name", None))

                    return Response(data)
                elif method in ["post"]:
                    return Response(api.create_resource(data))

            elif "additional_data" in path:
                return Response(api.additional_data(path[1]))
            else:
                id = path[1]
                if method in ["get"]:
                    return Response(api.detail(id))
                elif method in ["patch", "put"]:
                    return Response(api.update(id, data))
                elif method in ["delete"]:
                    return Response(api.delete(id))

        raise NotImplementedError(f"Request {method} {path} is not implemented on mocked api.")
