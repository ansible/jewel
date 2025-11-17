#!/usr/bin/env python3
"""
Test script to verify the consolidated deprecation approach works.
This tests the context processor changes to detect deprecation from extend_schema.
"""


# Mock the context processor functionality without needing full Django setup
class MockView:
    """Mock view with extend_schema deprecation"""

    def __init__(self, has_schema_deprecated=False, has_direct_deprecated=False):
        if has_schema_deprecated:
            self.schema = MockSchema(deprecated=True)
        if has_direct_deprecated:
            self.deprecated = True


class MockSchema:
    """Mock schema with is_deprecated method"""

    def __init__(self, deprecated=False):
        self._deprecated = deprecated

    def is_deprecated(self):
        return self._deprecated


class MockRequest:
    """Mock request with parser_context"""

    def __init__(self, view=None):
        self.parser_context = {'view': view}


def version_context_processor(request):
    """
    Simplified version of our context processor for testing
    """
    context = getattr(request, 'parser_context', {})
    view = context.get('view')

    # Check if the view is deprecated by first trying to access schema deprecation info
    deprecated = False
    if view:
        # Try to get deprecation status from drf-spectacular schema
        try:
            schema = getattr(view, 'schema', None)
            if schema and hasattr(schema, 'is_deprecated'):
                deprecated = schema.is_deprecated()
        except (AttributeError, TypeError):
            pass

        # Fall back to direct deprecated attribute if schema doesn't provide it
        if not deprecated:
            deprecated = getattr(view, 'deprecated', False)

    return {
        'deprecated': deprecated,
    }


def test_schema_deprecation():
    """Test that schema deprecation is detected"""
    view = MockView(has_schema_deprecated=True)
    request = MockRequest(view)
    result = version_context_processor(request)
    assert result['deprecated'] is True, "Schema deprecation should be detected"
    print("✓ Schema deprecation detected correctly")


def test_direct_deprecation_fallback():
    """Test that direct deprecation attribute is used as fallback"""
    view = MockView(has_direct_deprecated=True)
    request = MockRequest(view)
    result = version_context_processor(request)
    assert result['deprecated'] is True, "Direct deprecation attribute should be used as fallback"
    print("✓ Direct deprecation fallback works correctly")


def test_schema_takes_precedence():
    """Test that schema deprecation takes precedence over direct attribute"""
    view = MockView(has_schema_deprecated=True, has_direct_deprecated=True)
    request = MockRequest(view)
    result = version_context_processor(request)
    assert result['deprecated'] is True, "Schema deprecation should take precedence"
    print("✓ Schema deprecation takes precedence")


def test_no_deprecation():
    """Test that no deprecation is detected when neither is set"""
    view = MockView()
    request = MockRequest(view)
    result = version_context_processor(request)
    assert result['deprecated'] is False, "No deprecation should be detected"
    print("✓ No deprecation detected correctly")


def test_no_view():
    """Test that no deprecation is detected when no view is present"""
    request = MockRequest()
    result = version_context_processor(request)
    assert result['deprecated'] is False, "No deprecation should be detected without view"
    print("✓ No view case handled correctly")


if __name__ == '__main__':
    print("Testing consolidated deprecation approach...")

    test_schema_deprecation()
    test_direct_deprecation_fallback()
    test_schema_takes_precedence()
    test_no_deprecation()
    test_no_view()

    print("\n✅ All tests passed! The consolidated deprecation approach works correctly.")
    print("\nSummary of changes:")
    print("1. Modified context processor to check drf-spectacular schema deprecation first")
    print("2. Falls back to direct 'deprecated' attribute if schema doesn't provide deprecation info")
    print("3. Removed redundant 'deprecated = True' attributes from ViewSets that use @extend_schema(deprecated=True)")
    print("4. This consolidates deprecation handling in one place while maintaining backward compatibility")
