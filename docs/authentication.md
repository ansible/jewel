# Authentication

## Basic Auth

If a basic auth header is passed to the proxy the following logic applies.

First, the gateway will attempt to validate the header against its authentication mechanisms.
If that succeeds, the Authorization header will be stripped from the request and the JWT header will be add. Of course there is one exception, if the request is heading to /api/gateway the Authorization header will remain as the gateway does not authenticate with its own JWT tokens.

If the login fails, the Authorization header will be left in the request and the JWT header will *not* be added. The request with the Authorization header will be sent to the service allowing the service to attempt to authenticate the header.

## SAML


Security Assertion Markup Language (SAML) is an open standard for exchanging authentication and authorization data between parties, specifically between an identity provider (IdP) and a service provider (SP). It is commonly used for single sign-on (SSO) services to enable users to access multiple applications with one set of login credentials. SAML works by transferring the user's identity from one place (the IdP) to another (the SP) securely. This process involves the generation of an XML document by the IdP, which contains assertions about the user's identity, attributes, and entitlements. This SAML assertion is then digitally signed and sent to the SP, which, after verifying the assertion's authenticity, grants the user access to the application.


## OAuth2

https://oauth.net/2/

OAuth 2.0 is an industry-standard protocol for authorization, designed to enable secure, third-party access to user data without exposing user credentials. It specifies a process by which users can grant web and desktop applications permission to act on their behalf without sharing their password. Essentially, OAuth 2.0 allows an application (the client) to access resources (such as user data stored on a web server) through a series of interactions involving the resource owner (the user), the client, the authorization server, and the resource server. The protocol defines several grant types for different scenarios, including authorization code, implicit, password, and client credentials, each catering to specific types of client applications and security requirements. OAuth 2.0's flexibility and security have made it the foundation for numerous standards and frameworks, such as OpenID Connect for authentication. For technical documentation writers and quality engineers (QEs) tasked with setting up client configurations for OAuth, understanding these grant types, the flow of tokens, and the roles of different endpoints is crucial. Documentation must clearly articulate how to register applications with the authorization server, how to handle redirections and capture tokens, and how to securely store and use these tokens to access APIs, ensuring that the integration adheres to best practices for security and user privacy.


## Github OAuth2

The GitHub OAuth2 backend in social-core (a Python social authentication/registration mechanism used by the popular social-auth-app-django among others) simplifies the process of integrating GitHub authentication into your application. Unlike a full OAuth2 setup that requires handling various endpoints, secrets, and client IDs manually, configuring GitHub authentication with social-core primarily involves specifying a few key settings. Users need to register their application with GitHub to obtain a CLIENT_ID and CLIENT_SECRET, which are then used in the social-core configuration. Additionally, they must specify the SOCIAL_AUTH_GITHUB_KEY and SOCIAL_AUTH_GITHUB_SECRET settings with these values, and optionally, define the SOCIAL_AUTH_GITHUB_SCOPE to customize the permissions requested (e.g., accessing public info, user emails, etc.). This approach abstracts away much of the complexity of direct OAuth2 interactions, focusing instead on a straightforward setup that leverages social-core's built-in mechanisms for handling the OAuth2 flow, token exchange, and user data retrieval from GitHub. By doing so, it enables developers to quickly and securely add GitHub as an authentication method in their applications, enhancing the user experience by allowing users to sign in with their existing GitHub accounts.

https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app


### Authenticator plugin

An example authenticator payload ...

```
{
    "name": "github test",
    "type": "ansible_base.authentication.authenticator_plugins.github",
    "enabled": True,
    "order": 1,
    "configuration": {
        "KEY": "ASASDASDASD",
        "SECRET": "ADASDASDASDSA",
    }
}
```

## Github Enterprise OAuth2

When configuring OAuth2 authentication for GitHub and GitHub Enterprise within the `social-core` library, the primary difference lies in the endpoints and domain configurations due to GitHub Enterprise's self-hosted nature. Both backends require setting up OAuth2 credentials (like `CLIENT_ID` and `CLIENT_SECRET`), but GitHub Enterprise requires additional steps to specify the custom hostname of your enterprise instance. Here's a breakdown of the key configuration differences:

### GitHub OAuth2 Configuration:
For standard GitHub authentication, `social-core` provides a predefined backend that knows the default GitHub authorization and token exchange URLs (`https://github.com/login/oauth/authorize` and `https://github.com/login/oauth/access_token`, respectively). Users only need to provide the `SOCIAL_AUTH_GITHUB_KEY` and `SOCIAL_AUTH_GITHUB_SECRET` settings with their GitHub OAuth application's client ID and secret.

### GitHub Enterprise OAuth2 Configuration:
With GitHub Enterprise, you must configure the backend to point to your specific GitHub Enterprise instance's API endpoints. This means specifying the authorization, token, and user API endpoints according to your GitHub Enterprise's domain. For instance, if your GitHub Enterprise instance is hosted at `https://github.example.com`, you would configure endpoints like `https://github.example.com/login/oauth/authorize` and `https://github.example.com/login/oauth/access_token`. Additionally, you need to set `SOCIAL_AUTH_GITHUB_ENTERPRISE_KEY`, `SOCIAL_AUTH_GITHUB_ENTERPRISE_SECRET`, and `SOCIAL_AUTH_GITHUB_ENTERPRISE_API_URL` to reflect your custom GitHub Enterprise settings.

In summary, while both backends operate on the same OAuth2 principles, the GitHub Enterprise backend in `social-core` necessitates additional configuration to accommodate the custom domain and endpoints of an enterprise's self-hosted environment. This tailored setup ensures that the OAuth2 flow directs correctly to your enterprise's specific instance for authentication and token exchange processes, allowing seamless integration with the `social-core` library.

### Configuring the github enterprise system oauth app

https://docs.github.com/en/enterprise-server@3.12/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app

### Authenticator plugin

An example authenticator payload ...

```
{
    "name": "github enterprise test",
    "type": "ansible_base.authentication.authenticator_plugins.github_enterprise",
    "enabled": True,
    "order": 1,
    "configuration": {
        "URL: "https://github.mycorp.com",
        "API_URL": "https://github.mycorp.com/api",
        "KEY": "33b6fb2fde086aadca12",
        "SECRET": "8ccc3ab0038481522a6f9f4efed3cde99ad67902",
    }
}
```

## AzureAD OAuth2

Here's a look at what distinguishes the AzureAD backend from a generic OAuth2 backend in `social-core`:

### AzureAD Backend

- **Platform-Specific Features**: The AzureAD backend is designed specifically for integrating with Microsoft's Azure Active Directory, allowing applications to authenticate users against AzureAD. This includes support for Microsoft's v2.0 endpoint, which enables sign-in and permission requests using Microsoft's identity platform.
- **Configuration Details**: To configure the AzureAD backend, developers need to supply the application's `client_id`, `client_secret`, and `tenant_id`. The `tenant_id` can be a specific AzureAD tenant's directory ID or the common ID for multi-tenant applications.
- **Scopes and Permissions**: The AzureAD backend allows for specifying scopes that determine the level of access the application requests. This is particularly relevant for accessing various Microsoft services and APIs, as it uses Microsoft Graph permissions.
- **Token Acquisition and Refresh**: Handles the specifics of acquiring tokens from AzureAD, including refresh tokens, which are critical for maintaining access to resources without requiring the user to frequently re-authenticate.

### Key Differences

- **Specificity vs. Flexibility**: The AzureAD backend is specifically tailored for AzureAD and Microsoft's authentication workflows, making it easier to use for those services out of the box, with less configuration required around endpoints and Microsoft-specific scopes. In contrast, the OAuth2 backend offers greater flexibility but requires more detailed configuration and knowledge of the OAuth2 provider's API.
- **Platform-Specific Features**: AzureAD backend supports Microsoft-specific features and workflows, including multi-tenant configurations and integration with Microsoft Graph, which aren't directly applicable in a generic OAuth2 context.

In summary, while both backends facilitate OAuth2 authentication, the choice between them depends on the specific requirements of the service you're integrating with. If you're working with Azure Active Directory, the AzureAD backend simplifies setup and offers features tailored to Microsoft's ecosystem. For other OAuth2 services, the generic OAuth2 backend provides the necessary flexibility to integrate with a wide range of OAuth2 providers, at the cost of requiring more detailed configuration.

https://learn.microsoft.com/en-us/graph/auth-register-app-v2
https://support.smartbear.com/readyapi/docs/requests/auth/types/oauth2/tutorial-azure.html

### Authenticator plugin

An example authenticator payload ...

```
{
    "name": "github enterprise test",
    "type": "ansible_base.authentication.authenticator_plugins.azuread",
    "enabled": True,
    "order": 1,
    "configuration": {
        "CALLBACK_URL: "https://myapp.foobar.com/callback",
        "KEY": "33b6fb2fde086aadca12",
        "SECRET": "8ccc3ab0038481522a6f9f4efed3cde99ad67902",
    }
}
```

## Google OAuth2

https://support.google.com/cloud/answer/6158849?hl=en


### Authenticator plugin

An example authenticator payload ...

```
{
    "name": "github enterprise test",
    "type": "ansible_base.authentication.authenticator_plugins.google_oauth2",
    "enabled": True,
    "order": 1,
    "configuration": {
        "KEY": "33b6fb2fde086aadca12",
        "SECRET": "8ccc3ab0038481522a6f9f4efed3cde99ad67902",
    }
}
```

## OpenID Connect (OIDC)

https://openid.net/developers/how-connect-works/

OpenID Connect (OIDC) is both a derivative and a superset of OAuth 2.0, building upon the foundational OAuth 2.0 protocol to add an identity layer on top. While OAuth 2.0 is designed primarily for authorization, allowing applications to obtain access tokens to act on behalf of a user, OIDC extends this by adding user authentication. This means OIDC not only lets an application know that it has permission to access resources but also provides information about the identity of the user who has granted this permission.

The main difference between OAuth 2.0 and OIDC lies in this additional identity layer. OAuth 2.0 provides a framework for clients to access server resources on behalf of a resource owner, or by allowing the third-party application itself to gain access. It's all about resource access and sharing permissions without transferring user credentials. OIDC, on the other hand, introduces a new type of token: the ID token. This ID token is a JWT (JSON Web Token) and provides a standard set of claims about the authenticated user. While OAuth 2.0 tokens are meant for the application to communicate with the resource server, the ID token in OIDC is intended for the application itself, enabling it to authenticate the user.

In essence, while OAuth 2.0 focuses on client authorization without defining mechanisms for user authentication, OIDC builds upon OAuth 2.0 to provide a comprehensive solution that includes user authentication. This makes OIDC a more complete security protocol, suitable not just for authorizing application actions on behalf of the user but also for verifying who the user is, thereby enabling applications to manage user sessions and personalize user experiences more effectively.

In OIDC, the well-known URL ends with /.well-known/openid-configuration. This URL returns a JSON document containing configuration information about the OpenID Provider (OP). The openid-configuration JSON document serves as a discovery document that contains key details necessary for initiating the OpenID Connect authentication process, such as the URIs of the authorization endpoint, token endpoint, userinfo endpoint, and the public keys used for signing ID tokens. This allows client applications to programmatically discover the endpoints and key details of the OpenID Provider, facilitating dynamic configuration and easing integration efforts.

### Authenticator plugin

An example authenticator payload ...

```
{
    "name": "github enterprise test",
    "type": "ansible_base.authentication.authenticator_plugins.oidc",
    "enabled": True,
    "order": 1,
    "configuration": {
        "OIDC_ENDPOINT: "https://myoidc.foobar.com",
        "VERIFY_SSL": true,
        "KEY": "33b6fb2fde086aadca12",
        "SECRET": "8ccc3ab0038481522a6f9f4efed3cde99ad67902",
    }
}
```