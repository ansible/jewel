import pytest

from aap_gateway_api.utils.urls import remove_multiple_slashes_from_path


class TestRemoveMultipleSlashesFromPath:
    """
    Unit tests for the remove_multiple_slashes_from_path utility function.

    This function normalizes URL paths by collapsing consecutive slashes into a single slash.
    """

    @pytest.mark.parametrize(
        "input_path,expected_path,description",
        [
            ('/api//my-service//path//', '/api/my-service/path/', 'multiple double slashes at various positions'),
            ('/api/my-service//path', '/api/my-service/path', 'single double slash in middle of path'),
            ('//api//service//endpoint//', '/api/service/endpoint/', 'double slashes at start, middle, and end'),
            ('/api/my-service/path', '/api/my-service/path', 'normal path without double slashes (unchanged)'),
            ('/', '/', 'root path only'),
            ('//', '/', 'only double slashes'),
            ('////', '/', 'multiple consecutive slashes become single slash'),
            ('//////', '/', 'many consecutive slashes become single slash'),
            ('/api///service////endpoint/', '/api/service/endpoint/', 'varying numbers of consecutive slashes'),
            ('///', '/', 'three consecutive slashes'),
            ('/a//b///c////d/', '/a/b/c/d/', 'mixed single and multiple slashes'),
            ('', '', 'empty string'),
            ('api', 'api', 'no slashes'),
            ('/api/service/', '/api/service/', 'single trailing slash preserved'),
            ('/api/service', '/api/service', 'single leading slash preserved'),
            (None, None, 'None input returns None'),
        ],
    )
    def test_remove_multiple_slashes_from_path(self, input_path, expected_path, description):
        """
        Parameterized unit test for remove_multiple_slashes_from_path function.

        Tests the function with various path patterns including:
        - Multiple consecutive slashes at different positions
        - Normal paths that should remain unchanged
        - Edge cases like root path, empty string, all slashes, and None
        - Paths without slashes
        - Paths with single leading or trailing slashes
        """
        result = remove_multiple_slashes_from_path(input_path)
        assert result == expected_path, f"Failed for {description}: expected '{expected_path}' but got '{result}'"
