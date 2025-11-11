from aap_gateway_api.fields.serializers.multiple_choice_field import (
    MultipleChoiceFieldWithoutEmptyEnum,
)


class TestMultipleChoiceFieldWithoutEmptyEnum:
    """Tests for MultipleChoiceFieldWithoutEmptyEnum."""

    def test_spectacular_annotation_with_empty_choices(self):
        """Test that _spectacular_annotation returns array<string> when choices are empty."""
        field = MultipleChoiceFieldWithoutEmptyEnum(choices=[])
        annotation = field._spectacular_annotation

        assert annotation == {'field': {'type': 'array', 'items': {'type': 'string'}}}
        assert 'field' in annotation
        assert annotation['field']['type'] == 'array'
        assert annotation['field']['items']['type'] == 'string'

    def test_spectacular_annotation_with_non_empty_choices(self):
        """Test that _spectacular_annotation returns empty dict when choices exist."""
        field = MultipleChoiceFieldWithoutEmptyEnum(choices=[('option1', 'Option 1'), ('option2', 'Option 2')])
        annotation = field._spectacular_annotation

        # Should return empty dict to let drf-spectacular use default enum generation
        assert annotation == {}

    def test_spectacular_annotation_with_integer_choices(self):
        """Test that _spectacular_annotation returns empty dict when integer choices exist."""
        # Simulate choices like authenticator IDs (integers)
        field = MultipleChoiceFieldWithoutEmptyEnum(choices=[(1, 'Authenticator 1'), (2, 'Authenticator 2')])
        annotation = field._spectacular_annotation

        # Should return empty dict to let drf-spectacular use default enum generation
        assert annotation == {}

    def test_spectacular_annotation_with_string_choices(self):
        """Test that _spectacular_annotation returns empty dict when string choices exist."""
        field = MultipleChoiceFieldWithoutEmptyEnum(choices=[('value1', 'Label 1'), ('value2', 'Label 2')])
        annotation = field._spectacular_annotation

        # Should return empty dict to let drf-spectacular use default enum generation
        assert annotation == {}

    def test_spectacular_annotation_is_dict_for_empty_choices(self):
        """Test that _spectacular_annotation always returns a dict (not None) for empty choices."""
        field = MultipleChoiceFieldWithoutEmptyEnum(choices=[])
        annotation = field._spectacular_annotation

        # Must be a dict to avoid TypeError when drf-spectacular checks 'field' in annotation
        assert isinstance(annotation, dict)
        assert annotation is not None

    def test_spectacular_annotation_is_dict_for_non_empty_choices(self):
        """Test that _spectacular_annotation always returns a dict (not None) for non-empty choices."""
        field = MultipleChoiceFieldWithoutEmptyEnum(choices=[('option1', 'Option 1')])
        annotation = field._spectacular_annotation

        # Must be a dict to avoid TypeError when drf-spectacular checks 'field' in annotation
        assert isinstance(annotation, dict)
        assert annotation == {}
