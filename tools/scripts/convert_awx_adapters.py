#!/usr/bin/env python3

import json
import re
from os import environ, listdir
from sys import exit

testing = False

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


name_counter = 1


def build_attribute_map(session, data):
    global name_counter
    url = f'{session.base_url}/authenticator_maps/'
    data["name"] = f"Rule #{name_counter}"
    name_counter += 1
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
            "type": "ansible_base.authentication.authenticator_plugins.ldap",
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
            print("you will need to update the BIND_PASSWORD setting in your gateway adapter")
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


def import_saml_adapters(SAML_DATA=None):
    test_import = True
    idp_to_gateway_mapping = {
        "url": "IDP_URL",
        "x509cert": "IDP_X509_CERT",
        "entity_id": "IDP_ENTITY_ID",
        "attr_email": "IDP_ATTR_EMAIL",
        "attr_groups": "IDP_GROUPS",
        "attr_username": "IDP_ATTR_USERNAME",
        "attr_last_name": "IDP_ATTR_LAST_NAME",
        "attr_first_name": "IDP_ATTR_FIRST_NAME",
        "attr_user_permanent_id": "IDP_ATTR_USER_PERMANENT_ID",
    }

    if not SAML_DATA:
        print("Loading Controller SAML adapters")
        SAML_DATA = get_endpoint(sessions['CONTROLLER'], 'settings/saml')
        test_import = False

    for idp_name in SAML_DATA.get('SOCIAL_AUTH_SAML_ENABLED_IDPS', {}):
        adapter_name = f"Imported AWX SAML adapter {idp_name}"
        if adapter_name in authenticator_names:
            print(f"SAML Adapter {idp_name} already imported as {adapter_name}")
            continue

        print(f"Importing SAML Adapter {idp_name} as {adapter_name}")
        post_data = {
            "name": adapter_name,
            "enabled": False,
            "create_objects": SAML_DATA['SAML_AUTO_CREATE_OBJECTS'],
            "users_unique": False,
            "remove_users": False,
            "configuration": {},
            "type": "ansible_base.authentication.authenticator_plugins.saml",
        }
        for setting in [
            'SP_ENTITY_ID',
            'SP_PUBLIC_CERT',
            'SP_PRIVATE_KEY',
            'ORG_INFO',
            'TECHNICAL_CONTACT',
            'SUPPORT_CONTACT',
            'SECURITY_CONFIG',
            'SP_EXTRA',
            'EXTRA_DATA',
        ]:
            awx_setting_name = f"SOCIAL_AUTH_SAML_{setting}"
            if awx_setting_name in SAML_DATA:
                post_data['configuration'][setting] = SAML_DATA[awx_setting_name]

        public_cert = '-----BEGIN CERTIFICATE-----\nMIIDfTCCAmUCFDBBIcApOe69XBCGfsJsfHlXB8RsMA0GCSqGSIb3DQEBCwUAMHsx\nCzAJBgNVBAYTAlVTMRcwFQYDVQQIDA5Ob3J0aCBDYXJvbGluYTEPMA0GA1UEBwwG\nRHVyaGFtMRAwDgYDVQQKDAdBbnNpYmxlMRwwGgYDVQQLDBNHYXRld2F5IERldmVs\nb3BtZW50MRIwEAYDVQQDDAlsb2NhbGhvc3QwHhcNMjMxMTE0MjA0MzQyWhcNMjQx\nMTEzMjA0MzQyWjB7MQswCQYDVQQGEwJVUzEXMBUGA1UECAwOTm9ydGggQ2Fyb2xp\nbmExDzANBgNVBAcMBkR1cmhhbTEQMA4GA1UECgwHQW5zaWJsZTEcMBoGA1UECwwT\nR2F0ZXdheSBEZXZlbG9wbWVudDESMBAGA1UEAwwJbG9jYWxob3N0MIIBIjANBgkq\nhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAvYdZvKJPW8dzh5kDao30PA6Zoud0A42M\nzKiSNn8Z5A87zDJQK59MOBgkdBqdM2hvh7zXT/PdXJKIITgE6LUY3+dcICmVCOLz\nI9ik+nsmfgVOtTBbejDinjp442iF2aWrv2D2m0FASWrfp0++XEVd2xf+kIozaUdG\nKIr5VxDD6zfB1nUmxw0cRYmtOa7VY8dXEK4CYEGuriz9METrPdbFT4bcsNWPeZKc\nk47FTYXgVtb7PuHiTQ8F3iqwaEgiUFCkwR3bqYpQT4U/+1YTm1WjFOF2xK+SjPBY\neiqu9EnUXVrAX8VDLP6QHnXonpwnOnYqO1lxLEBpWpbXRD7+kg2u7wIDAQABMA0G\nCSqGSIb3DQEBCwUAA4IBAQCbQ107/cxfXJbOBHfBqUzaRbgFZW4WAhEx6YAt4TZI\npyp38VY71KPIL6RquLzUKBVv5UzJSH5++372XhT6aU/9KMoeiGa5oTNOmS9mFph1\nUy1Mccp8TFr9r4y+Ofek0lq4XSLK5u2YDYFb1SABkcmgE4AJ+eo2D1D6yp9lLVP/\nrS7ib5bwk+1tK0JATQTs9hmOwKhr7ey//Kb7ZxYcCdBG8bglJd9AfN/QObk4TzRI\nx0zDO/FOBy+rdOkwFYgaKuBwTWhSdqHDknBnJn4LqHWPmUIdv9Z4Q7zfU4YKUqOf\nua/7PZgwMf84hc89JJejbuX8bZENlP0XPBw37JkVGZfw\n-----END CERTIFICATE-----'  # noqa: E501

        # We are going to force the data in the SOCIAL_AUTH_SAML_ENABLED_IDPS into their own variables
        for key in idp_to_gateway_mapping:
            value = SAML_DATA['SOCIAL_AUTH_SAML_ENABLED_IDPS'][idp_name].get(key)
            if value is not None:
                post_data['configuration'][idp_to_gateway_mapping[key]] = value

        if test_import:
            # Lots of people don't put keys in support cases, so just add a dummy one here
            post_data['configuration']['IDP_X509_CERT'] = public_cert
            post_data['configuration']['IDP_URL'] = "https://www.example.com"

        # There are 2 fields in AWX that can be none but not in gateway
        for key, default in [('SP_EXTRA', {}), ('EXTRA_DATA', [])]:
            if not post_data['configuration'][key]:
                post_data['configuration'][key] = default

        # Next, we can't extract the private key and the public key is validated against the private key
        post_data['configuration'][
            'SP_PRIVATE_KEY'
        ] = '-----BEGIN PRIVATE KEY-----\nMIIEvwIBADANBgkqhkiG9w0BAQEFAASCBKkwggSlAgEAAoIBAQC9h1m8ok9bx3OH\nmQNqjfQ8Dpmi53QDjYzMqJI2fxnkDzvMMlArn0w4GCR0Gp0zaG+HvNdP891ckogh\nOATotRjf51wgKZUI4vMj2KT6eyZ+BU61MFt6MOKeOnjjaIXZpau/YPabQUBJat+n\nT75cRV3bF/6QijNpR0YoivlXEMPrN8HWdSbHDRxFia05rtVjx1cQrgJgQa6uLP0w\nROs91sVPhtyw1Y95kpyTjsVNheBW1vs+4eJNDwXeKrBoSCJQUKTBHdupilBPhT/7\nVhObVaMU4XbEr5KM8Fh6Kq70SdRdWsBfxUMs/pAedeienCc6dio7WXEsQGlaltdE\nPv6SDa7vAgMBAAECggEAJg+NVNVfjHXUXJG83uQc/QaNkepbIO+HK/5aRnll0KfC\ngXJFKU13N/iZMXu6v/0kEKU6tAKsHJAMqGcgjT74/NXwaUEQfdVdsIAsOWULyNj2\nAmrwo+w3RkFFz51I6/laMTeernT/HP9KZMYd21fOzlXWOF6YjnbSvweRpQtn3M9g\nCgbmQsFHi4DFbeubL1E2gZVZlmgdkR8OSMrym4/iROWxJD7E8sgeIn6kvUqexRQd\nh9JnUPfuPFa4DyZnnm7k3aSzvKoegbcVeMgWUXHphzWcQkG7rFjBsgcWaOh5Lr3x\nVTSywDHzVWTo1tnH59VohEnZxmSLHEj3Lqh7pYd/GQKBgQDqLqqz2ImmxOwl9kzn\nS+zijOFMYAmoRFJnw8GFlp9UGMAQYs8bIuY3GMdNZ+QVev9g1U80jyKZPPZ5/2kk\nD8qvy24kM1uMbi08ah7+8xhZd2ZCl7j9dIIJdqxbUWct6I0Dy4YV4smWGeZ6JgGE\naTNvinEUIgabIw7slUrUa0YgewKBgQDPL633bAXf9tW5jRVPFFMsjHBaMedNXhzO\nzvjHTw2f/7Xa6f0ESai9vPoEnBlDBBbi3r/hjZ7yBbDZdDPEVDK37iDRtsOfm0ms\nsyqcQxZsliA9auqGHcWMIlj9rjpQ4qSxVVIkk+UKXqeL9s/rDEoiKLOmHTlASIes\nmhHIgVKzHQKBgQCcrJgcNrTxVDJBu6T74focH/DjriUH5J3VOkyQ2ZLDKsPkspap\nKxImrnc4vFcGYAHXgR66pUCakQS93jkznTUXo9yOb6XCMDwnfUA7hdw2jwFlcCid\nuYL+Xd02QyHqvvkJHvMYVWBVAgMGmcLOGawF5fN9ar5MsIndkow7zYFfXQKBgQC3\nQGbQxtzTYVFcUuscDNAcQQNG44jAJ5O3X90u/D8C23uP6xH9buEvISzKUv8NBVrw\nwzBYYZjKXDo1u8/lwMszYA3rL4oLa6BYfggcOkJlPMu7Rwu0IDUQY3jut+GglTYy\nG1MSQzV8XIg5Bc6VCUOwvutW69Ytg3ltMsCz5Z6uCQKBgQDcpWSrGgOjPXuTjWYx\nFRB1oOwByGMKwu+TZWNLiMYOObGZ3j6+XxBFOcjdnrfLaePLRxYmgnWdkejlQOwy\nuGeaRDCFhv5BjCDWxq7hS8CVAZHivlUntmboU1Lq/MXw5czav+5QKPADYdWXW+0U\n7PXjjCwCbhb2GESpLxTXh55BgQ==\n-----END PRIVATE KEY-----'  # noqa: E501
        post_data['configuration']['SP_PUBLIC_CERT'] = public_cert

        # Import the ACS URL
        post_data['configuration']['CALLBACK_URL'] = SAML_DATA['SOCIAL_AUTH_SAML_CALLBACK_URL']

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
        print("you will need to update the SP cert and key")
        adapter_id = response.json()['id']
        print(f"Adapter number is {adapter_id}")

        # We have successfully imported the adapter so now lets import its rules
        order = 10

        if SAML_DATA.get('SOCIAL_AUTH_SAML_ORGANIZATION_MAP', None):
            for org_name, org_opts in SAML_DATA['SOCIAL_AUTH_SAML_ORGANIZATION_MAP'].items():
                remove = bool(org_opts.get('remove', True))
                organization_name = org_opts.get('organization_alias', org_name)

                for role in ['admins', 'users', 'auditors']:
                    # TODO: factor in roles here
                    is_member_expression = org_opts.get(role, None)
                    revoke = bool(org_opts.get('remove_users', remove))
                    if is_member_expression is None:
                        # You don't change anything on None so there is no map needed
                        pass
                    elif is_member_expression is True:
                        order = build_attribute_map(
                            sessions['GATEWAY'],
                            {
                                "authenticator": adapter_id,
                                "revoke": revoke,
                                "map_type": "organization",
                                "team": None,
                                "organization": organization_name,
                                "triggers": {"always": {}},
                                "order": order,
                            },
                        )
                    elif is_member_expression is False:
                        order = build_attribute_map(
                            sessions['GATEWAY'],
                            {
                                "authenticator": adapter_id,
                                "revoke": revoke,
                                "map_type": "organization",
                                "team": None,
                                "organization": organization_name,
                                "triggers": {"never": {}},
                                "order": order,
                            },
                        )
                    else:
                        if isinstance(is_member_expression, (str, type(re.compile('')))):
                            is_member_expression = [is_member_expression]
                        members = []
                        for expression in is_member_expression:
                            if isinstance(expression, str):
                                members.append(expression)
                            elif isinstance(expression, type(re.compile(''))):
                                order = build_attribute_map(
                                    sessions['GATEWAY'],
                                    {
                                        "authenticator": adapter_id,
                                        "revoke": revoke,
                                        "map_type": "organization",
                                        "team": None,
                                        "organization": organization_name,
                                        "triggers": {
                                            "attributes": {"join_condition": "or", "username": {"matches": expression}, "email": {"matches": expression}}
                                        },
                                        "order": order,
                                    },
                                )
                            else:
                                print(f"SOCIAL_AUTH_SAML_ORGANIZATION_MAP has invalid value expression {expression} in role {role} for {org_name}")
                                continue

                        if members:
                            order = build_attribute_map(
                                sessions['GATEWAY'],
                                {
                                    "authenticator": adapter_id,
                                    "revoke": revoke,
                                    "map_type": "organization",
                                    "team": None,
                                    "organization": organization_name,
                                    "triggers": {"attributes": {"join_condition": "or", "username": {"in": members}, "email": {"in": members}}},
                                    "order": order,
                                },
                            )

        if SAML_DATA.get('SOCIAL_AUTH_SAML_TEAM_MAP', None):
            for team_name, team_opts in SAML_DATA['SOCIAL_AUTH_SAML_TEAM_MAP'].items():
                if 'organization' not in team_opts:
                    print(f"Team {team_name} in SOCIAL_AUTH_SAML_TEAM_MAP is invalid due to missing organization")
                    continue

                remove = bool(org_opts.get('remove', True))
                organization_name = org_opts.get('organization')

                for role in ['users']:
                    # TODO: factor in roles here
                    is_member_expression = org_opts.get('users', None)
                    revoke = bool(org_opts.get('remove_users', remove))
                    if is_member_expression is None:
                        # You don't change anything on None so there is no map needed
                        pass
                    elif is_member_expression is True:
                        order = build_attribute_map(
                            sessions['GATEWAY'],
                            {
                                "authenticator": adapter_id,
                                "revoke": revoke,
                                "map_type": "team",
                                "team": team_name,
                                "organization": organization_name,
                                "triggers": {"always": {}},
                                "order": order,
                            },
                        )
                    elif is_member_expression is False:
                        order = build_attribute_map(
                            sessions['GATEWAY'],
                            {
                                "authenticator": adapter_id,
                                "revoke": revoke,
                                "map_type": "team",
                                "team": team_name,
                                "organization": organization_name,
                                "triggers": {"never": {}},
                                "order": order,
                            },
                        )
                    else:
                        if isinstance(is_member_expression, (str, type(re.compile('')))):
                            is_member_expression = [is_member_expression]
                        for expression in is_member_expression:
                            if isinstance(expression, str):
                                trigger = {"attributes": {"join_condition": "or", "username": {"equals": expression}, "email": {"equals": expression}}}
                            elif isinstance(expression, type(re.compile(''))):
                                trigger = {"attributes": {"join_condition": "or", "username": {"matches": expression}, "email": {"matches": expression}}}
                            else:
                                print(f"SOCIAL_AUTH_SAML_TEAM_MAP has invalid value expression {expression} in role {role} for {org_name}")
                                continue

                            order = build_attribute_map(
                                sessions['GATEWAY'],
                                {
                                    "authenticator": adapter_id,
                                    "revoke": revoke,
                                    "map_type": "team",
                                    "team": team_name,
                                    "organization": organization_name,
                                    "triggers": trigger,
                                    "order": order,
                                },
                            )

        if SAML_DATA.get('SOCIAL_AUTH_SAML_ORGANIZATION_ATTR', None):
            # TODO: How do we do this one?
            if SAML_DATA['SOCIAL_AUTH_SAML_ORGANIZATION_ATTR'] != {}:
                print("WARNING: SOCIAL_AUTH_SAML_ORGANIZATION_ATTR can not automatically be processed, you will need to update your authenticator maps")

        if SAML_DATA.get('SOCIAL_AUTH_SAML_TEAM_ATTR', None):
            saml_attr = SAML_DATA['SOCIAL_AUTH_SAML_TEAM_ATTR'].get('saml_attr', None)
            if saml_attr:
                revoke = SAML_DATA['SOCIAL_AUTH_SAML_TEAM_ATTR'].get('remove', True)
                for team_name_map in SAML_DATA['SOCIAL_AUTH_SAML_TEAM_ATTR'].get('team_org_map', []):
                    team_name = team_name_map.get('team', None)
                    team_alias = team_name_map.get('team_alias', team_name)
                    organization_name = team_name_map.get('organization', None)
                    if not team_name and not organization_name:
                        print(f"In SOCIAL_AUTH_SAML_TEAM_ATTR there is an invalid entry {team_name_map}")
                        continue
                    order = build_attribute_map(
                        sessions['GATEWAY'],
                        {
                            "authenticator": adapter_id,
                            "revoke": revoke,
                            "map_type": "team",
                            "team": team_alias,
                            "organization": organization_name,
                            "triggers": {"attributes": {"join_condition": "or", saml_attr: {"equals": team_name}}},
                            "order": order,
                        },
                    )

        if SAML_DATA.get('SOCIAL_AUTH_SAML_USER_FLAGS_BY_ATTR'):
            for role in ['superuser', 'system_auditor']:
                revoke = SAML_DATA['SOCIAL_AUTH_SAML_USER_FLAGS_BY_ATTR'].get(f'remove_{role}s', True)

                if f'is_{role}_role' in SAML_DATA['SOCIAL_AUTH_SAML_USER_FLAGS_BY_ATTR']:
                    roles = SAML_DATA['SOCIAL_AUTH_SAML_USER_FLAGS_BY_ATTR'][f'is_{role}_role']
                    if type(roles) is not list:
                        roles = [roles]

                    for saml_role in roles:
                        order = build_attribute_map(
                            sessions['GATEWAY'],
                            {
                                "authenticator": adapter_id,
                                "revoke": revoke,
                                "map_type": f"is_{role}",
                                "team": None,
                                "organization": None,
                                "triggers": {
                                    "groups": {
                                        "has_or": roles,
                                    }
                                },
                                "order": order,
                            },
                        )

                attribute = SAML_DATA['SOCIAL_AUTH_SAML_USER_FLAGS_BY_ATTR'].get(f'is_{role}_attr', None)
                values = SAML_DATA['SOCIAL_AUTH_SAML_USER_FLAGS_BY_ATTR'].get(f'is_{role}_value', None)
                if type(values) is not list and values is not None:
                    values = [values]

                if attribute:
                    if not values:
                        # If we don't have values we just have the trigger get {} which will just check for the presence of the value
                        values = {}
                    else:
                        values = {"in": values}

                    order = build_attribute_map(
                        sessions['GATEWAY'],
                        {
                            "authenticator": adapter_id,
                            "revoke": revoke,
                            "map_type": f"is_{role}",
                            "team": None,
                            "organization": None,
                            "triggers": {"attributes": {"join_condition": "or", attribute: values}},
                            "order": order,
                        },
                    )


def import_settings():
    settings = get_endpoint(sessions['CONTROLLER'], 'settings/all')
    settings_to_convert = [
        ("LOGIN_REDIRECT_OVERRIDE", "LOGIN_REDIRECT_OVERRIDE"),
        ("SOCIAL_AUTH_USERNAME_IS_FULL_EMAIL", "SOCIAL_AUTH_USERNAME_IS_FULL_EMAIL"),
        ("LOCAL_PASSWORD_MIN_LENGTH", "password_min_length"),
        ("LOCAL_PASSWORD_MIN_DIGITS", "password_min_digits"),
        ("LOCAL_PASSWORD_MIN_UPPER", "password_min_upper"),
        ("LOCAL_PASSWORD_MIN_SPECIAL", "password_min_special"),
        ("CUSTOM_LOGIN_INFO", "custom_login_info"),
        ("CUSTOM_LOGO", "custom_logo"),
    ]
    gateway_settings = {}
    for awx_setting_name, gateway_setting_name in settings_to_convert:
        gateway_settings[gateway_setting_name] = settings[awx_setting_name]

    url = f"{sessions['GATEWAY'].base_url}/settings/all/"
    response = sessions['GATEWAY'].put(url, json=gateway_settings, verify=sessions['GATEWAY'].verify)
    if response.status_code != 200:
        print("Failed to copy over settings:")
        print(response.status_code)
        print(response.text)


authenticator_names = []
authenticators = load_all(sessions['GATEWAY'], 'authenticators')
for authenticator in authenticators:
    authenticator_names.append(authenticator['name'])


if testing:
    for file in listdir():
        if not file.endswith(".json"):
            continue
        print(f"Trying {file}")
        with open(file, 'r') as f:
            string_data = f.read()
            try:
                json_data = json.loads(string_data)
            except Exception as e:
                print(f"Unable to read {file} as json {e}")
                continue

        import_saml_adapters(json_data)
        next = input("Press enter for next import")
else:
    import_ldap_adapters()
    import_saml_adapters()
    import_settings()
