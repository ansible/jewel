# AAP Gateway DRF Integration

If you are using the Django Rest Framework for your API you can use this library as a simple way to integrate your application with AAP Gateway's authentication mechanism.

# Build this library
There is a make target to build this form the root of the git project:
```
make build_service-lib
```

This will make library packages files in service_lib/dist/ which you can add to your application.

# Usage

This library integrates with the AAP Gateway to provide JWT authentication with your service. The JWT token will provide all of the required user information (see Token Definition section) including attributes and org/team mapping. Your application is responsible for taking the information and mapping the local users respectively. The library is very customizable via function override. 

There are 3 mandatory steps to integrate your service with the library and one optional:
 * Construct an Authentication Class
 * Add URLs
 * Add Settings
 * Customize the login view (optional)

## Authentication Class

First, you will want to create a class for processing the claims that come from the gateway. You will want to extend our base class like:

```
from aap.gateway import JWTAuthentication

class MyAppIntegrationAuthenticationClass(JWTAuthentication):
    def process_permissions(self, user, claims):
        # user will be the user object we authenticated 
        # claims will be a dict representing the claims from the gateway

        # In here process the claims field to your content
```

Note: The parent gateway classes will also map known fields from the gateway token into the user object. These can also be overridden. See the Token Definition section for details.


## URLs

Next, in your api's `urls.py` we are going to add a login view for the proxy:
```
    from aap.gateway.urls import GatewayURLs
    urls.extend(GatewayURLs().get_url_list())
```

If you are extending the login view (see below) you can specify that in the class constructor:
```
    from aap.gateway.urls import GatewayURLs
    from awx.api.views.gateway import AWXLoggedGatewayLoginView

    urls.extend(GatewayURLs(login_view_class=AWXLoggedGatewayLoginView).get_url_list())
```

NOTE: The gateway library will add a gateway path into your api and this endpoint must be at `https://<host>/api/gateway/`

## Settings

Finally, we need to add some settings to your django app to configure it to use the gateway. 

First, add a setting called `AAP_GATEWAY_KEY` to tell your application how to find the decryption key for the JWT token. This setting supports three methods:
 * A url like `https://<gateway>`. This should be up to but not including the `/jwt_key/` path. Using this the code will make an HTTP request out to the server to retrieve the signing key.  You can also set `AAP_GATEWAY_VALIDATE_CERT` to `False` if you need to ignore the cert on the URL.
 * A url like `file:///my/path`. This will tell the code to load the signing certificate form a file on disk.
 * The cert itself as a string. This would hard code the cert for the application.

Secondly, we need to add your custom authentication class to the `REST_FRAMEWORK__DEFAULT_AUTHENTICATION_CLASSES` setting. You will want to add your custom class /under/ whatever SessionAuthentication you use. If you place it before that you will process the JWT token on every request to the service which will decrease the performance significantly.

Example:

```
REST_FRAMEWORK__DEFAULT_AUTHENTICATION_CLASSES = [
    "rest_framework.authentication.BasicAuthentication",
    "rest_framework.authentication.SessionAuthentication",
    "galaxy_ng.app.auth.auth.MyCustomGatewayLoginClass",  # <- This is the gateway class we extended
]
```

### Logging
If you want to add some messages about the auth process the gateway library uses a logger with a path of `aap.gateway` so add something like this to your loggers:
```
        'aap': {'handlers': ['console', 'file', 'tower_warnings', 'external_logger'], 'level': 'DEBUG'},
```

## Login view (Optional)
if you want to override our view (say to add additional headers) you can subclass it like:
```
from aap.gateway.views import LoggedGatewayLoginView
class AWXLoggedGatewayLoginView(LoggedGatewayLoginView):
    authentication_classes=[AwxAAPGatewayAuthentication]

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        if response.status_code == 200:
            response.set_cookie('userLoggedIn', 'true')
            response.setdefault('X-API-Session-Cookie-Name', getattr(settings, 'SESSION_COOKIE_NAME', 'awx_sessionid'))
        return response
```

NOTE: this view uses the backend `django.contrib.auth.backends.ModelBackend` if you want to override with your own backend you can add the following attribute to the class
```
backend = '<your backend here>'
```



# Token definition
By default the following fields will come from the JWT token and be mapped into the User object:

| JWT Field         | User Attribute    |
| ----------------- | ----------------- |
| sub               | username          |
| first_name        | first_name        |
| last_name         | last_name         |
| email             | email             |
| is_superuser      | is_superuser      |
| is_system_auditor | is_system_auditor |

With the exception of `sub` mapping to `username` the other fields could be changed if desired.

For example, lets say your service does not have the concept of `is_system_auditor`. To do this, we can override a field called `map_fields` on your classes that override `JWTAuthentication` with this line:
```
from aap.gateway import JWTAuthentication

class MyGatewayAuthentication(JWTAuthentication):
    map_fields = ['first_name', 'last_name', 'email', 'is_superuser']
``` 

Note: if you add a new field in here you will need to work with the gateway team because these fields have to be present inside the JWT token or an exception will be thrown saying the token is invalid.

If, you needed to do more powerful processing for the user mapping you can not only override the fields but also override the `process_user_data` in the same fields. The default implementation is:
```
    def process_user_data(self, user, token):
        common_auth = GatewayCommonAuth(self.mapped_fields)
        common_auth.map_user_fields(user, token)
```

This method takes the user object (either existing or created) and also the JWT token with all of its fields and claims. The common_auth.map_user_fields maps the fields from the token into the user field. If you override this method you can control if/how the fields from the JWT token map into the user object. for example, if I didn't want any user mapping fields at all I could just:
```
    def process_user_data(self, user, token):
        pass
```

# Org/Team Mapping

<TBD>
