import sys

from django.apps import AppConfig


class MyAppConfig(AppConfig):
    name = 'aap_gateway_api'
    verbose_name = "Ansible Automation Platform Gateway"

    def ready(self):
        # Do not run this if we are running a manage command. Otherwise we get chicken and egg issues because the startup calls gateway-manage migrate
        if not sys.argv[0].endswith(('manage.py', 'pytest')):
            from aap_gateway_api.utils.preferences import initialize_preferences

            initialize_preferences()
