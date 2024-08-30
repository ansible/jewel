# Putting this in a separate file from the legacy_auth fixture so that it can be
# imported by the gateway tests.

from collections import namedtuple

SSOProvider = namedtuple("SSOProvider", ["backend", "name"])

kc = SSOProvider("keycloak", "keycloak_vanilla")
saml_kc = SSOProvider("saml", "KeycloakSAML")
oidc_kc = SSOProvider("oidc", "keycloak_oidc")
shib = SSOProvider("saml", "Shibboleth")


class Account:
    def __init__(self, backend, preferred_username, sub, password, username=None):
        self.backend = backend
        self.preferred_username = preferred_username
        self.sub = sub
        self.password = password
        self.username = username

    def get_uid(self):
        provider = self.backend.backend
        if provider == "saml":
            return f"{self.backend.name}:{self.preferred_username}"
        elif provider == "oidc":
            return self.sub
        elif provider == "keycloak":
            return self.preferred_username

    def get_extra_data(self):
        provider = self.backend.backend
        if provider in ("keycloak", "oidc"):
            return {
                "sub": self.sub,
                "preferred_username": self.preferred_username,
            }
        else:
            return {}


USERS = {
    "user1": {
        "awx": Account(oidc_kc, "user1", "bdfef522-0aec-491b-b721-9107f6f08fa7", None),
        "galaxy": Account(None, None, None, "pass"),
        "eda": Account(None, None, None, "pass"),
    },
    "user2": {
        "awx": Account(None, None, None, "pass"),
        "galaxy": Account(kc, "user2", "5260abd4-ad23-4592-a45b-603382f7b56e", None),
        "eda": Account(None, None, None, "pass"),
    },
    "user3": {
        "awx": Account(saml_kc, "user3", "9188d3c9-7c00-4d3a-a75c-112d1e5917f4", None),
        "galaxy": Account(None, None, None, "pass"),
        "eda": Account(None, None, None, "pass"),
    },
    "user4": {
        "awx": Account(shib, "user4", "d01aa274-5ea6-4551-bc89-0de736dca17a", None),
        "galaxy": Account(None, None, None, "pass2"),
        "eda": Account(None, None, None, "pass"),
    },
    "user5": {
        "awx": Account(None, None, None, "pass"),
        "galaxy": Account(None, None, None, "pass"),
        "eda": Account(None, None, None, "pass"),
    },
    "user6": {
        "awx": Account(None, None, None, "pass3"),
        "galaxy": Account(None, None, None, "pass2"),
        "eda": Account(None, None, None, "pass1"),
    },
    "user7": {
        "awx": Account(None, None, None, "pass3"),
        "galaxy": Account(None, None, None, "pass2"),
        "eda": Account(None, None, None, "pass1"),
    },
    "conflict1": {
        "awx": Account(None, None, None, "pass3"),
        "galaxy": Account(None, None, None, "pass2"),
        "eda": Account(None, None, None, "pass1"),
    },
    "conflict2": {
        "awx": Account(None, None, None, "pass3"),
        "galaxy": Account(None, None, None, "pass2"),
        "eda": Account(None, None, None, "pass1"),
    },
    "conflict3": {
        "awx": Account(oidc_kc, "conflict_uid1", "4c37820d-5f71-44ba-bec2-796505d1272e", None),
        "galaxy": Account(kc, "conflict_uid1", "4c37820d-5f71-44ba-bec2-796505d1272e", None),
        "eda": Account(None, None, None, "pass1"),
    },
    "already_linked1": {
        "awx": Account(None, None, None, "pass3"),
        "galaxy": Account(None, None, None, "pass2"),
    },
    "already_linked2": {
        "eda": Account(None, None, None, "pass3"),
        "galaxy": Account(None, None, None, "pass2"),
    },
    "different_username1": {
        "galaxy": Account(None, None, None, "pass2"),
    },
    "different_username2": {
        "eda": Account(None, None, None, "pass2"),
    },
    "different_username3": {
        "awx": Account(None, None, None, "pass2"),
    },
    "two_sso1": {
        "awx": Account(oidc_kc, "two_sso1", "4b4614e7-7086-496a-a4d5-694206b3f844", None),
        "galaxy": Account(kc, "two_sso1", "4b4614e7-7086-496a-a4d5-694206b3f844", None),
    },
    "two_sso2": {
        "awx": Account(saml_kc, "two_sso2", "441fc82c-2196-45c6-9ced-ce4fecd996ad", None),
        "galaxy": Account(kc, "two_sso2", "441fc82c-2196-45c6-9ced-ce4fecd996ad", None),
    },
    "two_sso3": {
        "awx": Account(shib, "two_sso3", "e50aa50b-7b54-4faa-8096-319ea4590ad8", None),
        "galaxy": Account(kc, "two_sso3", "e50aa50b-7b54-4faa-8096-319ea4590ad8", None),
    },
    "disable_login": {
        "awx": Account(None, None, None, "pass"),
        "galaxy": Account(kc, "disable_login", "7b6939d0-dee4-4c24-8dd0-42e8484a7d1b", None),
    },
    "1fake_new_user": {
        "awx": Account(oidc_kc, "fake_new_user", "1b60016a-dbd7-4906-bca2-8aeb49e0441b", None),
    },
    "2fake_new_user": {
        "galaxy": Account(None, None, None, "pass2"),
    },
    "3fake_new_user": {
        "eda": Account(None, None, None, "pass1"),
    },
}

for username in USERS:
    for service in USERS[username]:
        USERS[username][service].username = username

USER_SETS = {
    "controller_oidc": (("user1", "*"),),
    "hub_keycloak": (("user2", "*"),),
    "controller_saml": (("user3", "*"),),
    "password_set_1": (("user4", "*"),),
    "password_set_2": (("user5", "*"),),
    "password_set_3": (("user6", "*"),),
    "password_set_4": (("user7", "*"),),
    "conflict_all1": (
        ("conflict1", "awx"),
        ("conflict2", "galaxy"),
        ("conflict3", "eda"),
    ),
    "conflict_all2": (
        ("conflict2", "awx"),
        ("conflict3", "galaxy"),
        ("conflict1", "eda"),
    ),
    "conflict_all3": (
        ("conflict3", "awx"),
        ("conflict1", "galaxy"),
        ("conflict2", "eda"),
    ),
    "already_linked1": (
        ("already_linked1", "galaxy"),
        ("already_linked1", "awx"),
    ),
    "already_linked2": (("already_linked2", "galaxy"),),
    "already_linked3": (("already_linked2", "eda"),),
    "different_uesernames": (
        ("different_username1", "galaxy"),
        ("different_username2", "eda"),
        ("different_username3", "awx"),
    ),
    "two_sso_oidc": (("two_sso1", "*"),),
    "two_sso_saml_kc": (("two_sso2", "*"),),
    "two_sso_saml_ext": (("two_sso3", "*"),),
    "disable_login": (("disable_login", "*"),),
    "fake_new_user": (
        ("1fake_new_user", "awx"),
        ("2fake_new_user", "galaxy"),
        ("3fake_new_user", "eda"),
    ),
}


def get_user_set(key) -> dict[str, Account]:
    user_set = {}
    for username, service in USER_SETS[key]:
        if service == "*":
            user_set = {**user_set, **USERS[username]}
        else:
            user_set[service] = USERS[username][service]

    return user_set
