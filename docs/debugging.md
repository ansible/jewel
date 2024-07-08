# Debugging

In the dev environment (built by default) we install [remote-pdb](https://pypi.org/project/remote-pdb/). 

We also set environment variables for integrating with pythons `breakpoint` so you can just add a line anywhere needed like:
```
breakpoint()
```


When the code hits that point it should stop and start remote-pdb on port 4444. This port is exposed through the container.

You can use any method you like to connect to remote-pdb (see remote-pdb docs for ideas).


### Using `pytest`

We use `pytest` to run our tests. To run all tests, use the following command:

```bash
tox -e 311
```

To run a specific test, use:

```bash
tox -e 311 -- -k <testname>
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
- Run `tox -e 311` to execute all tests.
- Run `tox -e 311 -- -k <testname>` to execute a specific test.
- Remove the `-n auto` option in `pyproject.toml` to avoid issues with parallel execution.
- If breakpoints are not being hit, disable coverage options during debugging.
