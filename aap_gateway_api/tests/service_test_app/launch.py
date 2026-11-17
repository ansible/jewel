import os
import subprocess
import sys
import tempfile
import time

import requests

services = {"awx", "galaxy", "eda"}
_SERVICE_START_TIMEOUT_SECONDS = 60
_SERVICE_START_POLL_INTERVAL_SECONDS = 0.25


def _collect_process_output(proc):
    output_files = getattr(proc, "_service_test_output_files", None)
    if not output_files:
        return None, None

    output = []
    for stream in output_files:
        stream.flush()
        stream.seek(0)
        output.append(stream.read())
        stream.close()
    proc._service_test_output_files = None
    return output


def stop_service(proc):
    """Stop a test service and return captured stdout/stderr, if enabled."""
    if proc.poll() is None:
        proc.kill()
    proc.wait()
    stdout, stderr = _collect_process_output(proc)
    return stdout, stderr


def _print_process_output(stdout, stderr):
    if stdout:
        print('')
        print('standard out:')
        print(str(stdout, encoding='utf-8'))
    if stderr:
        print('')
        print('standard err:')
        print(str(stderr, encoding='utf-8'))


def launch_service(service_type, port, setup_fixture=None, dev_mode=False, secret_key=None, save_std=True, user_prefix='controller', page_size=None):
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
    env["RENAMED_USERNAME_PREFIX"] = user_prefix

    if not dev_mode:
        from aap_gateway_api.utils.preferences import get_preference_value

        public_key = get_preference_value("proxy", "jwt_public_key", encrypted=False)
        if public_key == '':
            # Sometimes, if a test is wrapped in a transaction it may have an empty key, so we need to add one
            from aap_gateway_api.utils.jwt_token import generate_jwt_keypair
            from aap_gateway_api.utils.preferences import update_preference_value

            key_pair = generate_jwt_keypair()
            update_preference_value("proxy", "jwt_private_key", key_pair.private)
            update_preference_value("proxy", "jwt_public_key", key_pair.public)

        env["ANSIBLE_BASE_JWT_KEY"] = get_preference_value("proxy", "jwt_public_key", encrypted=False)
    else:
        env["SERVICE_TEST_APP_DEV_MODE"] = "true"
        env["ANSIBLE_BASE_JWT_KEY"] = ""

    if secret_key:
        env["SERVICE_TEST_APP_SECRET_KEY"] = secret_key
    else:
        env["SERVICE_TEST_APP_SECRET_KEY"] = "secret"

    if setup_fixture:
        env["SERVICE_TEST_APP_FIXTURE"] = setup_fixture

    if page_size:
        env["REST_FRAMEWORK_PAGE_SIZE"] = str(page_size)

    # Remove any existing settings modules from the environment so that we don't confuse manage.py
    if "DJANGO_SETTINGS_MODULE" in env:
        del env["DJANGO_SETTINGS_MODULE"]

    # Threading has to be disable because we're using an in memory database that doesn't get shared
    # between threads.
    if save_std:
        stdout_stream = tempfile.TemporaryFile()
        stderr_stream = tempfile.TemporaryFile()
    else:
        stdout_stream = stderr_stream = subprocess.DEVNULL

    try:
        proc = subprocess.Popen(
            ["python3", "manage.py", "runserver", "--nothreading", "--noreload", str(port)],
            cwd=dir_path,
            env=env,
            stderr=stderr_stream,
            stdout=stdout_stream,
        )
    except Exception:
        if save_std:
            stdout_stream.close()
            stderr_stream.close()
        raise

    proc._service_test_output_files = (stdout_stream, stderr_stream) if save_std else None

    deadline = time.monotonic() + _SERVICE_START_TIMEOUT_SECONDS
    url = f"http://localhost:{port}/ping/"
    while True:
        try:
            requests.get(url, timeout=1)
            break
        except requests.RequestException:
            pass

        if proc.poll() is not None:
            stdout, stderr = stop_service(proc)
            _print_process_output(stdout, stderr)
            raise Exception(f"service_test_app for service {service_type} on port {port} exited with code {proc.returncode} before becoming ready")

        if time.monotonic() >= deadline:
            stdout, stderr = stop_service(proc)
            _print_process_output(stdout, stderr)
            raise Exception(f"service_test_app for service {service_type} on port {port} failed to come online within {_SERVICE_START_TIMEOUT_SECONDS} seconds")

        time.sleep(_SERVICE_START_POLL_INTERVAL_SECONDS)

    return proc


def main():
    # Defaults to 'migration_tests',
    setup_fixure = 'migration_tests'
    if len(sys.argv) == 2:
        setup_fixure = sys.argv[1]

    print(f"Launching with setup from fixtures/{setup_fixure}.py")
    print(f"To use a different fixture, specify its name (without the .py), e.g. {sys.argv[0]} migration_tests_invalid_users")
    proc = launch_service("awx", "5630", dev_mode=True, setup_fixture=setup_fixure)
    print("Running on localhost:5630, username:dev_admin, password:admin")
    while True:
        try:
            time.sleep(5)
        except:  # noqa E722
            stdout, stderr = stop_service(proc)
            _print_process_output(stdout, stderr)
            break


if __name__ == '__main__':
    main()
