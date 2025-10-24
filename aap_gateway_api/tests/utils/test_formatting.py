import pytest

from aap_gateway_api.utils.formatting import normalize_comma_separated_list


class TestNormalizeCommaSeparatedList:
    """Test the normalize_comma_separated_list utility function."""

    @pytest.mark.parametrize(
        "input_value,expected_output",
        [
            # Normal cases
            ('tag1,tag2,tag3', 'tag1,tag2,tag3'),
            ('tag1, tag2, tag3', 'tag1,tag2,tag3'),
            ('  tag1  ,  tag2  ,  tag3  ', 'tag1,tag2,tag3'),
            # Empty values
            ('tag1,,tag2', 'tag1,tag2'),
            ('tag1, , tag2', 'tag1,tag2'),
            (',,tag1,,,tag2,,', 'tag1,tag2'),
            # Edge cases - should return empty string for CharField compatibility (blank=True, null=False)
            ('', ''),
            ('   ', ''),
            (',,,', ''),
            ('tag1', 'tag1'),
            ('  tag1  ', 'tag1'),
            # None values - should return empty string
            (None, ''),
        ],
    )
    def test_normalize_comma_separated_list(self, input_value, expected_output):
        """Test that comma-separated lists are normalized correctly."""
        result = normalize_comma_separated_list(input_value)
        # Now that we preserve order, we can do direct string comparison
        assert result == expected_output

    def test_normalize_removes_duplicates(self):
        """Test that duplicate values are removed while preserving first occurrence order."""
        result = normalize_comma_separated_list('tag1,tag2,tag1,tag3,tag2')
        # Should preserve order of first occurrence: tag1, tag2, tag3
        assert result == 'tag1,tag2,tag3'

    @pytest.mark.parametrize(
        "input_value,expected_output",
        [
            # Order preservation tests
            ('z,y,x,w', 'z,y,x,w'),  # Reverse alphabetical order preserved
            ('apple,zebra,banana,cat', 'apple,zebra,banana,cat'),  # Mixed order preserved
            ('3,1,4,1,5,9,2,6', '3,1,4,5,9,2,6'),  # Numbers with dupe, first occurrence kept
            ('last,middle,first,middle,last', 'last,middle,first'),  # Duplicates at different positions
        ],
    )
    def test_order_preservation(self, input_value, expected_output):
        """Test that insertion order is preserved (not alphabetical or other sorting)."""
        result = normalize_comma_separated_list(input_value)
        assert result == expected_output
