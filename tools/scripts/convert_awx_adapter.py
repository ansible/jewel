#!/usr/bin/env python3

from os import environ
from sys import exit

errors = []

try:
    import requests
except ImportError:
    errors.append("You need the requests package installed")

supported_products = ["CONTROLLER", "GATEWAY"]
for product in supported_products:
    for setting in ['HOST', 'USERNAME', 'PASSWORD', 'VERIFY_SSL']:
        env_var_name = f"{product}_{setting}"
        if not environ.get(env_var_name, None):
            errors.append(f'You must have the {env_var_name} environment variable set')

sessions = {}
if not errors:
    for product in supported_products:
        sessions[product] = requests.Session()
        sessions[product].auth = (environ.get(f'{product}_USERNAME'), environ.get(f'{product}_PASSWORD'))
        if environ.get(f'{product}_VERIFY_SSL').lower() == "false":
            sessions[product].verify = False
            requests.packages.urllib3.disable_warnings()

        if product == 'GATEWAY':
            sessions[product].base_url = f"{environ.get(f'{product}_HOST')}/api/gateway/v1"
            url = f"{sessions[product].base_url}/organizations/"
        elif product == 'CONTROLLER':
            sessions[product].base_url = f"{environ.get(f'{product}_HOST')}/api/v2"
            url = f"{sessions[product].base_url}/organizations/"

        try:
            response = sessions[product].get(url, verify=sessions[product].verify)
            if response.status_code != 200:
                errors.append(f'Failed to log into {product}. Expected 200 got back {response.status_code}')
        except Exception as e:
            errors.append(f'Failed to log into {product}: {e}')

if errors:
    print("Errors:")
    print('\n'.join(errors))
    exit(255)


def load_all(session, endpoint):
    objects = []
    page = 1
    more = True
    while more:
        url = f"{session.base_url}/{endpoint}/?page={page}"
        response = session.get(url, verify=session.verify)
        data = response.json()
        objects.extend(data['results'])
        if data['next']:
            more = True
            page = page + 1
        else:
            more = False
    return objects


def get_endpoint(session, endpoint):
    url = f"{session.base_url}/{endpoint}/"
    response = session.get(url, verify=session.verify)
    return response.json()


def build_attribute_map(session, data):
    url = f'{session.base_url}/authenticator_maps/'
    response = session.post(url, json=data, verify=session.verify)
    if response.status_code != 201:
        print(f"Failed to add attribute map ({response.status_code}):")
        print(data)
        try:
            print(response.json())
        except Exception as e:
            print(e)
            print(response.text)
    return data['order'] + 10


def import_ldap_adapters():
    print("Loading Controller LDAP adapters")
    LDAP_DATA = get_endpoint(sessions['CONTROLLER'], 'settings/ldap')
    for adapter_number in ['', '_1', '_2', '_3', '_4', '_5']:
        if not LDAP_DATA[f"AUTH_LDAP{adapter_number}_SERVER_URI"]:
            print(f"LDAP Adapter {adapter_number} is not configured in Controller, skipping")
            continue
        friendly_number = adapter_number.replace('_', '')
        adapter_name = f"Imported AWX LDAP adapter {friendly_number}"
        if adapter_name in authenticator_names:
            print(f"LDAP Adapter {friendly_number} already imported as {adapter_name}")
            continue

        print(f"Importing LDAP Adapter {friendly_number} as {adapter_name}")
        post_data = {
            "name": adapter_name,
            "enabled": False,
            "create_objects": True,
            "users_unique": False,
            "remove_users": False,
            "configuration": {},
            "type": "l",
        }
        for setting in [
            'BIND_DN',
            'START_TLS',
            'CONNECTION_OPTIONS',
            'USER_SEARCH',
            'USER_DN_TEMPLATE',
            'USER_ATTR_MAP',
            'GROUP_SEARCH',
            'GROUP_TYPE',
            'GROUP_TYPE_PARAMS',
        ]:
            awx_setting_name = f"AUTH_LDAP{adapter_number}_{setting}"
            if awx_setting_name in LDAP_DATA:
                post_data['configuration'][setting] = LDAP_DATA[awx_setting_name]

        # We can't extract the password so we are just going to make one up
        post_data['configuration']['BIND_PASSWORD'] = 'password'

        # SERVER_URI used to be a string but now its an array and we know it has to be in here because of the check above
        # In awx if it was an array it would be separated by ', '
        post_data['configuration']['SERVER_URI'] = LDAP_DATA[f"AUTH_LDAP{adapter_number}_SERVER_URI"].split(", ")

        endpoint = f"{sessions['GATEWAY'].base_url}/authenticators/"
        response = sessions['GATEWAY'].post(endpoint, verify=sessions['GATEWAY'].verify, json=post_data)
        if response.status_code != 201:
            print("Failed to import the adapter:")
            try:
                print(response.json())
            except Exception:
                print(response.text)
            continue

        print("Import successful!")
        if f"AUTH_LDAP{adapter_number}_BIND_PASSWORD" in LDAP_DATA:
            print("you will need to update the BIND_PASSWORD setting in your Gateway adapter")
        adapter_id = response.json()['id']
        print(f"Adapter number is {adapter_id}")

        # We have successfully imported the adapter so now lets import its rules
        order = 10
        if f"AUTH_LDAP{adapter_number}_USER_FLAGS_BY_GROUP" in LDAP_DATA:
            for flag in LDAP_DATA[f"AUTH_LDAP{adapter_number}_USER_FLAGS_BY_GROUP"]:
                groups = LDAP_DATA[f"AUTH_LDAP{adapter_number}_USER_FLAGS_BY_GROUP"][flag]
                if type(groups) is str:
                    groups = [groups]

                # TODO: Confirm these can be not groups and that has_or and revoke is correct
                order = build_attribute_map(
                    sessions['GATEWAY'],
                    {
                        "authenticator": adapter_id,
                        "revoke": True,
                        "map_type": flag,
                        "team": None,
                        "organization": None,
                        "triggers": {
                            "groups": {
                                "has_or": groups,
                            }
                        },
                        "order": order,
                    },
                )

        if f"AUTH_LDAP{adapter_number}_ORGANIZATION_MAP" in LDAP_DATA:
            for organization_name in LDAP_DATA[f"AUTH_LDAP{adapter_number}_ORGANIZATION_MAP"].keys():
                organization = LDAP_DATA[f"AUTH_LDAP{adapter_number}_ORGANIZATION_MAP"][organization_name]
                for user_type in ['admins', 'users']:
                    if user_type in organization:
                        # TODO: Confirm that if we have None with remove we still won't remove
                        if organization[user_type] is None:
                            continue

                        if organization[user_type] is False:
                            triggers = {"never": {}}
                        elif organization[user_type] is True:
                            triggers = {"always": {}}
                        else:
                            if type(organization[user_type]) is str:
                                organization[user_type] = [organization[user_type]]

                            triggers = {"groups": {"has_or": organization[user_type]}}

                        order = build_attribute_map(
                            sessions['GATEWAY'],
                            {
                                "authenticator": adapter_id,
                                "revoke": organization.get(f'remove_{user_type}', False),
                                "map_type": "team",
                                "team": f"Organization {user_type.title()}",
                                "organization": organization_name,
                                "triggers": triggers,
                                "order": order,
                            },
                        )

        if f"AUTH_LDAP{adapter_number}_TEAM_MAP" in LDAP_DATA:
            for team_name in LDAP_DATA[f"AUTH_LDAP{adapter_number}_TEAM_MAP"].keys():
                team = LDAP_DATA[f"AUTH_LDAP{adapter_number}_TEAM_MAP"][team_name]
                # TODO: Confirm that if we have None with remove we still won't remove
                if team['users'] is None:
                    continue

                if team['users'] is False:
                    triggers = {"never": {}}
                elif team['users'] is True:
                    triggers = {"always": {}}
                else:
                    if type(team['users']) is str:
                        team['users'] = [team['users']]

                    triggers = {"groups": {"has_or": team['users']}}

                order = build_attribute_map(
                    sessions['GATEWAY'],
                    {
                        "authenticator": adapter_id,
                        "revoke": team.get('remove', False),
                        "map_type": "team",
                        "team": team_name,
                        "organization": team.get('organization', 'You have a team with no organization'),
                        "triggers": triggers,
                        "order": order,
                    },
                )

        require_group = LDAP_DATA.get(f"AUTH_LDAP{adapter_number}_REQUIRE_GROUP", None)
        if require_group:
            order = build_attribute_map(
                sessions['GATEWAY'],
                {
                    "authenticator": adapter_id,
                    "revoke": False,
                    "map_type": "allow",
                    "team": None,
                    "organization": None,
                    "triggers": {"groups": {"has_and": [require_group]}},
                    "order": order,
                },
            )

        deny_group = LDAP_DATA.get(f"AUTH_LDAP{adapter_number}_DENY_GROUP", None)
        if deny_group:
            order = build_attribute_map(
                sessions['GATEWAY'],
                {
                    "authenticator": adapter_id,
                    "revoke": False,
                    "map_type": "allow",
                    "team": None,
                    "organization": None,
                    "triggers": {"groups": {"has_not": [require_group]}},
                    "order": order,
                },
            )


authenticator_names = []
authenticators = load_all(sessions['GATEWAY'], 'authenticators')
for authenticator in authenticators:
    authenticator_names.append(authenticator['name'])

import_ldap_adapters()
