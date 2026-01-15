# Debugging

## PDB Breakpoints

In the dev environment (built by default) we install [remote-pdb](https://pypi.org/project/remote-pdb/). 

We also set environment variables for integrating with pythons `breakpoint` so you can just add a line anywhere needed like:
```
breakpoint()
```

When the code hits that point it should stop and start remote-pdb on port 4444. This port is exposed through the container.

You can use any method you like to connect to remote-pdb (see remote-pdb docs for ideas).

## VSCode Integration

You can also debug visually via debugpy and VSCode.
In the `.vscode` directory there are launch and tasks json files which configure a VSCode integration. In the VS Debugger window there are two configurations for debugging:
* Debug Gateway API
* Debug Gateway Control Plane

Select which piece of gateway you want to debug and click the run button.
This will do the following:
1. Execute a playbook to:
  1. Stop the "normal" services
  2. Start the "debug" services
  3. Wait for the debugpy port to be opened (3000 for the Django API and 3001 for GRPC Control plane)
1. Attach to the debugpy port
1. Begin the debugging session in VSCode
1. At the end of the session, execute another playbook to:
  1. Stop the "debug" services
  1. Start the "normal" services

The "debug" services are just single threaded versions of Django and GRPC to enable the attachment of the debugger. The playbook to put gateway in and out of this state can also be manually run:
```
ansible-playbook tools/ansible/switch_gateway_mode.yml -e mode=[debug|normal] -e service=[api|control-plane]
```

NOTE: nginx still runs in both cases and envoy can route traffic to either the normal or debug services.


### Using `pytest`

We use `pytest` to run our tests. To run all tests, use the following command:

```bash
tox -e py312
```

To run a specific test, use:

```bash
tox -e py312 -- -k <testname>
```

### Important Notes:

- In `pyproject.toml`, you can see the following command:

```bash
 commands =
         ./tools/scripts/ci/tox-reinstall-django-ansible-base.sh {envname}
         pytest -n auto --cov=. --cov-report=xml:coverage.xml --cov-report=html --cov-report=json --cov-branch {env:GATEWAY_TEST_DIRS:aap_gateway_api/tests} {posargs}
```

Option: `-n auto`  will run tests in parallel using all available CPUs, which can lead to issues such as:

1. **Loss of stdout/stderr control**: When tests are run in parallel, the output from different tests may interleave, making it difficult to read and understand the test results. This loss of control over standard output and error can lead to confusion and make debugging more challenging.
2. **Coverage issues**: The `pytest-cov` plugin, which is used for measuring code coverage, may not work correctly with parallel test execution. It can result in incomplete or inaccurate coverage reports.
3. **Debugging difficulties**: Parallel execution can prevent reaching breakpoints predictably.

If you encounter these issues, you can remove the `-n auto option` from your `pyproject.toml` or command line to run tests sequentially, which may help mitigate these problems.

### Summary

- Use `breakpoint()` to set breakpoints in your code.
- `remote-pdb` will listen on port 4444 for remote debugging.
- Run `tox -e py312` to execute all tests.
- Run `tox -e py312 -- -k <testname>` to execute a specific test.
- Remove the `-n auto` option in `pyproject.toml` to avoid issues with parallel execution.
- If breakpoints are not being hit, disable coverage options during debugging.
