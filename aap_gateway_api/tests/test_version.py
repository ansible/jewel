import re
from io import StringIO
from unittest import mock

from aap_gateway_api.version import get_aap_version, get_api_version


def test_get_api_version_from_version_file():
    expected_version = "2.6.0"
    with mock.patch("importlib.metadata.version", side_effect=Exception), mock.patch("builtins.open", return_value=StringIO(expected_version)):
        assert get_api_version() == expected_version


def test_get_api_version_from_package_version():
    expected_version = "2.999.0"
    with mock.patch("importlib.metadata.version", return_value=expected_version):
        assert get_api_version() == expected_version


def test_get_api_version_fallback():
    "setuptools_scm not installed in unit test suite, so test for last fallback version string"
    with mock.patch("importlib.metadata.version", side_effect=Exception), mock.patch("os.path.exists", return_value=False):
        assert get_api_version() == "Unknown"


def test_get_aap_version():
    """
    This should test the get_aap_version function and verify that it
    returns a x.y version string and that it is a substring of get_api_version.
    """
    aap_version = get_aap_version()
    assert aap_version in get_api_version()
    assert re.match("^[0-9]+[.]{1}[0-9]+$", aap_version) is not None


def test_get_aap_version_error_case():
    with mock.patch("aap_gateway_api.version.get_api_version", return_value="development"):
        aap_version = get_aap_version()
        assert aap_version == "development"
