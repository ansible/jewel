import pytest

from aap_gateway_api.fields.serializers.multiple_choice_field import MultipleChoiceFieldWithoutEmptyEnum

EXPECTED_ANNOTATION = {'field': {'type': 'array', 'items': {'type': 'integer'}, 'nullable': True}}


class TestMultipleChoiceFieldWithoutEmptyEnum:
    """Tests for MultipleChoiceFieldWithoutEmptyEnum."""

    @pytest.mark.parametrize(
        "choices",
        [
            pytest.param([], id="empty_choices"),
            pytest.param([('option1', 'Option 1'), ('option2', 'Option 2')], id="string_choices"),
            pytest.param([(1, 'Authenticator 1'), (2, 'Authenticator 2')], id="integer_choices"),
        ],
    )
    def test_spectacular_annotation(self, choices):
        """Test that _spectacular_annotation always returns a fixed array<integer> schema."""
        field = MultipleChoiceFieldWithoutEmptyEnum(choices=choices)
        annotation = field._spectacular_annotation

        assert isinstance(annotation, dict)
        assert annotation == EXPECTED_ANNOTATION
