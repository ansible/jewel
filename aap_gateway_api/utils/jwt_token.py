import logging
from collections import namedtuple
from datetime import datetime, timedelta

import jwt
from ansible_base.rbac.models import RoleDefinition
from ansible_base.resource_registry.models import Resource, service_id
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.contenttypes.models import ContentType
from django.db.models import F, Model, OuterRef

from aap_gateway_api.utils.preferences import get_preference_value, update_preference_value

logger = logging.getLogger('aap.gateway.utils.jwt_token')


def create_signed_jwt(user, resource_api_actions=None):
    """
    Create a signed JWT token for the given user

    The format of the current token is:
    {
        "version": "1",
        "iss": "ansible-issuer",
        "exp": int(due_date.timestamp()),
        "aud": "ansible-services",
        "sub": str(user.resource.ansible_id),
        "service_id": str(user.resource.service_id),
        "user_data": {
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "is_superuser": user.is_superuser,
        },
        "objects": {
            "<object_content_type (i.e. organization)>": [ <- Each entry holds an array of anything needed to create the object type
                {
                    <ansible_id>: <value>,
                    <name>: <value>,
                }, ...
            ]
            "<object_content_type (i.e. team)>": [
                {
                    <ansible_id>: <value>,
                    <name>: <value>,
                    <organization>: <index of organization from objects.organization above>
                },
                ...
            ]
        "object_roles": {
            "<role name>": {
                "content_type": (entry pointer object above),
                "objects": [<index of organization from objects.organization above>],
            },
            ...
        },
        "global_roles": ["<role name>", ...],
    }
    """

    from aap_gateway_api.models import Organization, Team

    due_date = datetime.now() + timedelta(seconds=get_preference_value("proxy", "gateway_access_token_expiration"))
    payload = {
        "version": "1",
        "iss": "ansible-issuer",
        "exp": int(due_date.timestamp()),
        "aud": "ansible-services",
        "sub": str(user.resource.ansible_id),
        "service_id": str(service_id()),
        "user_data": {
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "is_superuser": user.is_superuser,
        },
        "objects": {},
        "object_roles": {},
        "global_roles": [],
    }

    cached_objects_index = {}  # Entries like { <content_model>: {<ansible_id>: <array index integer> } } used to resolve ansible_ids to array indexes
    cached_content_types = {}  # Entries like { <content id integer>: <content_model> } used to resolve a content id to a model type
    for content_type in ContentType.objects.all().values('id', 'model'):
        content_type_id = content_type['id']
        model = content_type['model']
        cached_content_types[content_type_id] = model
        cached_objects_index[model] = {}

    required_data = {}  # Entries like { <content_model>: { <ansible_id>|<id>: <required_data> } } Note: required_data could have references to ansible_ids

    # Populate the required_data for orgs
    org_content_type_model = ContentType.objects.get_for_model(Organization).model
    required_data[org_content_type_model] = {}
    for org in Organization.objects.all().values('id', 'name', 'resource__ansible_id'):
        org_id = org['id']
        name = org['name']
        ansible_id = str(org['resource__ansible_id'])
        required_data[org_content_type_model][org_id] = {'ansible_id': ansible_id, 'name': name}
        required_data[org_content_type_model][ansible_id] = required_data[org_content_type_model][org_id]
    payload['objects'][org_content_type_model] = []

    # Populate the required_Data for teams
    team_content_type_model = ContentType.objects.get_for_model(Team).model
    required_data[team_content_type_model] = {}
    for team in Team.objects.all().values('id', 'name', 'resource__ansible_id', 'organization__resource__ansible_id'):
        team_id = team['id']
        team_name = team['name']
        ansible_id = str(team['resource__ansible_id'])
        related_org_ansible_id = str(team['organization__resource__ansible_id'])
        required_data[team_content_type_model][team_id] = {'ansible_id': ansible_id, 'name': team_name, 'org': related_org_ansible_id}
        required_data[team_content_type_model][ansible_id] = required_data[team_content_type_model][team_id]
    payload['objects'][team_content_type_model] = []

    # We will now scan Org and Team roles and get users memberships to them.
    user_object_roles = get_user_object_roles(user)
    for role_name, ansible_id, content_type_id in user_object_roles:
        # Get the model for this content_type
        content_model_type = cached_content_types[content_type_id]

        # If the ansible_id is not in the cached_objects_index
        if ansible_id not in cached_objects_index[content_model_type]:
            # Cache the index the current len will be the next index when we append
            cached_objects_index[content_model_type][ansible_id] = len(payload['objects'][content_model_type])
            # Add the object to the payloads objects
            payload['objects'][content_model_type].append(required_data[content_model_type][ansible_id])

        # Get the index value we want from the cache
        object_index = cached_objects_index[content_model_type][ansible_id]

        # If the role is not in the payload, insert it
        if role_name not in payload['object_roles']:
            payload['object_roles'][role_name] = {'content_type': content_model_type, 'objects': []}

        # The object is the object cache
        payload['object_roles'][role_name]['objects'].append(object_index)

    # Now we are going to trim up any team references to organizations with the index instead of the ansible ID
    # i.e. we currently have entries like: payload['objects']['team'][0]['org'] = <ansible_id>
    # and we are going to convert that to: payload['objects']['team'][0]['org'] = 0

    for team in payload['objects'][team_content_type_model]:
        org_ansible_id = team['org']
        if org_ansible_id in cached_objects_index[org_content_type_model]:
            team['org'] = cached_objects_index[org_content_type_model][org_ansible_id]
        else:
            # The user is in a team related to an org but we didn't pull that org in yet
            # Cache the index of the org, which is the current len
            cached_objects_index[org_content_type_model][org_ansible_id] = len(payload['objects'][org_content_type_model])
            org_data = required_data[org_content_type_model][org_ansible_id]
            team['org'] = len(payload['objects'][org_content_type_model])
            payload['objects'][org_content_type_model].append(org_data)

    # See if the user has any global roles
    for rd in RoleDefinition.objects.filter(content_type=None, user_assignments__user=user.pk):
        payload['global_roles'].append(rd.name)

    if resource_api_actions:
        payload["resource_api_actions"] = resource_api_actions

    token = jwt.encode(payload, get_jwt_rsa_key(public=False), algorithm='RS256')
    return token


def get_user_object_roles(user: Model) -> list[tuple[str, str, int]]:
    """Returns a list of tuples giving (role name, ansible_id, content_type_id)

    This data is the role name joined with data about the resource"""
    resource_qs = Resource.objects.filter(object_id=OuterRef('object_id'), content_type=OuterRef('content_type')).values('ansible_id')
    assignment_qs = user.role_assignments.filter(content_type__isnull=False).annotate(aid=resource_qs, rd_name=F('role_definition__name'))
    return [(ra.rd_name, str(ra.aid), ra.content_type_id) for ra in assignment_qs]


def decode_signed_jwt(token):
    return jwt.decode(token, get_jwt_rsa_key(public=True), algorithms=['RS256'], audience='ansible-services')


def get_jwt_rsa_key(public=False):
    if public:
        pub_key = get_preference_value("proxy", "jwt_public_key", encrypted=False)
        # Just in case the public key is not yet loaded into preferences regenerate the key and get it into the cache
        if not pub_key:
            key_to_return = update_jwt_public_key(get_preference_value("proxy", "jwt_private_key", encrypted=False))
        else:
            key_to_return = pub_key
    else:
        key_to_return = get_preference_value("proxy", "jwt_private_key", encrypted=False)

    return key_to_return


def update_jwt_public_key(new_private_key):
    try:
        private_key = serialization.load_pem_private_key(bytes(new_private_key, "UTF-8"), password=None)
    except Exception as e:
        logger.exception("Unable to load private key from JWT key")
        raise e

    try:
        public_key = (
            private_key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )
        update_preference_value("proxy", "jwt_public_key", public_key)
    except Exception as e:
        logger.exception("Unable to export public key from JWT key")
        raise e

    return public_key


def generate_jwt_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    private_key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    RSAKeyPair = namedtuple("RSAKeyPair", ["private", "public"])
    return RSAKeyPair(private=private_key_bytes, public=public_key_bytes)
