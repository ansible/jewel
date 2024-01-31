# Authentication

## Basic Auth

If a basic auth header is passed to the proxy the following logic applies.

First, the gateway will attempt to validate the header against its authentication mechanisms.
If that succeeds, the Authorization header will be stripped from the request and the JWT header will be add. Of course there is one exception, if the request is heading to /api/gateway the Authorization header will remain as the gateway does not authenticate with its own JWT tokens.

If the login fails, the Authorization header will be left in the request and the JWT header will *not* be added. The request with the Authorization header will be sent to the service allowing the service to attempt to authenticate the header.
