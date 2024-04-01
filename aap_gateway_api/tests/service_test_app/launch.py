import os
import subprocess
import time

import requests

from aap_gateway_api.utils.preferences import get_preference_value

services = {"awx", "galaxy", "eda"}


def launch_service(service_type, port, setup_fixture=None):
    """
    This launches the service_test_app in a sub process.

    service_type: one of "awx", "galaxy", "eda".
    port: port that the service should run on.
    setup_fixture: the name of a module in aap_gateway_api.tests.service_test_app.fixtures to run
        to set up test data. This module must define a "setup()" function that will get called
        when the test app starts up. See migration_tests.py for an example.
    """
    dir_path = os.path.dirname(os.path.realpath(__file__))

    assert service_type in services

    # copy the env so that we get the correct tox python venv.
    env = os.environ.copy()
    env["SERVICE_TEST_APP_TYPE"] = service_type
    env["ANSIBLE_BASE_JWT_KEY"] = get_preference_value("proxy", "jwt_public_key", encrypted=False)

    if setup_fixture:
        env["SERVICE_TEST_APP_FIXTURE"] = setup_fixture

    # Remove any existing settings modules from the environment so that we don't confuse manage.py
    del env["DJANGO_SETTINGS_MODULE"]

    # Threading has to be disable because we're using an in memory database that doesn't get shared
    # between threads.
    proc = subprocess.Popen(
        ["python3", "manage.py", "runserver", "--nothreading", "--noreload", str(port)],
        cwd=dir_path,
        env=env,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )

    count = 0
    max_count = 20
    while True:
        try:
            requests.get(f"http://localhost:{port}/ping/")
            break
        except requests.ConnectionError:
            pass

        if count >= max_count:
            proc.kill()
            raise Exception("service_test_app failed to come online")
        count += 1
        time.sleep(0.5)

    return proc
