Notes about legacy auth:

All actions take place from the perspective of the logged in user.
If a logged in user (a user who already has a Gateway session) uses the legacy
auth endpoints and authenticates to a service, it indicates that they are trying
to link their service account to their existing gateway account.

The model `MigratedUserMetadata` represents users' accounts on other AAP
services. Most likely the instance is created by the `migrate_service_data`
management command, though it could also be done by the legacy auth
endpoints. The reverse relation here is `User#original_accounts`. So if you have
a **gateway user**, then accessing `.original_accounts` will get you metadata
about their original service accounts.

Importantly, the `migrate_service_data` command will create one
`MigratedUserMetadata` row for each (service, user) combination, and the
corresponding Gateway user will be created immediately before, if it does not
yet exist.

When you access `/legacy_auth/` as a gateway user, you'll get a list of accounts
that have been "linked" to the current user. The "linking" is identified by the
existence of `MigratedUserMetadata` rows and each linked account is a
representation of such a row:

1. `LinkedAccountSerializer`'s model is `MigratedUserMetadata`
2. `LegacyAuthSerializer` (which is `/legacy_auth/`'s serializer) uses
   `LinkedAccountSerializer` to render the `linked_accounts` field.

Now then, we trace the password authentication, as that is relevant to the
ticket I am working.

There is an `authenticate_password` action in `LegacyAuthViewset`. Through
standard serializer usage, it accepts as input a username and password, along
with a service type to authenticate to (corresponding to the service clusters
known to Gateway).

First off, we need to state that this endpoint can be used by a logged in user
with a Gateway session, but also by a logged out user attempting to
authenticate.

- **If the user is NOT logged in to Gateway**: This process will log them in to
  gateway, assuming their authentication against the service was successful.
- **If the user IS logged in to Gateway**: This process will try to link their
  service account (the one they are providing credentials for) to their
  currently logged in account. (In the code the currently logged in account is
  sometimes called the "`main_account`").

When a POST request comes in with this data, Gateway will (synchronously, mind
you) use its internal "Service Resource API client" to ask the specified service
if the given username and password combination is valid. If it's not, we stop
here.

If it's valid, Gateway will get an "auth code" back from the service. (This is a
JWT token, but that doesn't matter, except for noting that data can be conveyed
in it which is useful.) In this case, we do "stuff" with the auth code and then
redirect the user back to `/legacy_auth/` to see their (possibly newly) linked
account.

The details get more complex when we examine that "stuff". First off, as part of
the information we get back in the auth code, we get the service user's
`ansible_id`. This is important, because as part of validating the token, we
ensure that the `ansible_id` we get back is known to Gateway.

So we'll make use of two terms here:
- I will call the currently logged in to Gateway user the **session user**
- I will call the user whose `ansible_id` we get back from the service the
  **service user**.

The quick rundown of the steps:

- Ensure the auth code token is even valid and hasn't been manipulated, and that
  the service user's `ansible_id` is known to Gateway (either created during
  `migrate_service_data` or during a reverse sync operation from a service).
- Check if the service user is "allowed" to log in (more on this soon). Bail out
  now if not.
- If the service user has no `MigratedUserMetadata` rows (linked accounts) at
  all:
    - Gateway will now create one. Note that at this point in
      the process, nothing is tying this service user to the session user. Gateway
      _knows_ about the service user (it has a `User` row for it, otherwise
      validation would not have let the auth code token through), but it does not
      know that it is in any way related to the session user.
    - An `Authenticator` row (cooresponding to the service's password auth) is
      created if it doesn't yet exist.
    - An `AuthenticatorUser` is created, tying the service user to the
      `Authenticator` indicating that it authenticates using the service's password
      auth.
- Finally, if there _is_ a session user, Gateway will attempt to link the
  service user to it. Otherwise, Gateway will simply log the session user in
  (again, it knows about the user already, by `ansible_id`), and the session
  user will become the service user.

There's some stuff to unpack here. So: We get a service user's `ansible_id` back
from the service after authentication, and we resolve that to a Gateway `User`
(possibly a skeleton `User` created by `migrate_service_data`). So why do we
check for `service_user.original_accounts.exists()` and only create
`MigratedUserMetadata` if it doesn't?

 This block of code only exists for the case of reverse-sync-created users. If a
 user is created with `migrate_service_data`, it will already have a
 `MigratedUserMetadata` attached. But if the service user's counterpart was
 created in Gateway via a reverse sync operation, then it might not have a
 `MigratedUserMetadata`, so this is our chance to create it.

...
