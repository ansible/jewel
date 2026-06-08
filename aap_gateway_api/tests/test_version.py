from importlib.metadata import PackageNotFoundError
from io import StringIO
from unittest import mock

from aap_gateway_api.version import generate_version, get_aap_version, get_api_version


class TestGenerateVersion:
    def test_reads_from_version_file(self):
        expected_version = "1.0.0"
        with (
            mock.patch("os.path.exists", return_value=True),
            mock.patch("builtins.open", return_value=StringIO(expected_version)),
        ):
            assert generate_version() == expected_version

    def test_strips_whitespace_from_version_file(self):
        with (
            mock.patch("os.path.exists", return_value=True),
            mock.patch("builtins.open", return_value=StringIO("  1.0.0\n  ")),
        ):
            assert generate_version() == "1.0.0"

    def test_falls_back_to_setuptools_scm(self):
        scm_version = "0.1.dev1+gabcdef"
        fake_scm = mock.MagicMock(get_version=mock.Mock(return_value=scm_version))
        with (
            mock.patch("os.path.exists", return_value=False),
            mock.patch.dict("sys.modules", {"setuptools_scm": fake_scm}),
        ):
            assert generate_version() == scm_version

    def test_returns_unknown_when_nothing_available(self):
        with (
            mock.patch("os.path.exists", return_value=False),
            mock.patch.dict("sys.modules", {"setuptools_scm": None}),
        ):
            assert generate_version() == "Unknown"


class TestGetApiVersion:
    def test_returns_package_version(self):
        expected_version = "3.0.0"
        with mock.patch("importlib.metadata.version", return_value=expected_version):
            assert get_api_version() == expected_version

    def test_falls_back_to_generate_version_on_exception(self):
        with (
            mock.patch("importlib.metadata.version", side_effect=PackageNotFoundError),
            mock.patch("aap_gateway_api.version.generate_version", return_value="1.2.3") as mock_gen,
        ):
            assert get_api_version() == "1.2.3"
            mock_gen.assert_called_once()

    def test_returns_version_file_content_when_package_unavailable(self):
        expected_version = "1.0.0"
        with (
            mock.patch("importlib.metadata.version", side_effect=PackageNotFoundError),
            mock.patch("os.path.exists", return_value=True),
            mock.patch("builtins.open", return_value=StringIO(expected_version)),
        ):
            assert get_api_version() == expected_version

    def test_returns_unknown_as_last_resort(self):
        with (
            mock.patch("importlib.metadata.version", side_effect=PackageNotFoundError),
            mock.patch("os.path.exists", return_value=False),
            mock.patch.dict("sys.modules", {"setuptools_scm": None}),
        ):
            assert get_api_version() == "Unknown"


class TestGetAapVersion:
    def test_extracts_major_minor_from_semver(self):
        with mock.patch("aap_gateway_api.version.get_api_version", return_value="3.2.1"):
            assert get_aap_version() == "3.2"

    def test_extracts_major_minor_from_four_part_version(self):
        with mock.patch("aap_gateway_api.version.get_api_version", return_value="1.2.3.4"):
            assert get_aap_version() == "1.2"

    def test_returns_full_string_for_single_component(self):
        with mock.patch("aap_gateway_api.version.get_api_version", return_value="Unknown"):
            assert get_aap_version() == "Unknown"

    def test_returns_full_string_for_non_dotted_version(self):
        with mock.patch("aap_gateway_api.version.get_api_version", return_value="development"):
            assert get_aap_version() == "development"

    def test_handles_two_part_version(self):
        with mock.patch("aap_gateway_api.version.get_api_version", return_value="1.0"):
            assert get_aap_version() == "1.0"
