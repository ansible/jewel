import importlib
import inspect
import pkgutil

import pytest
from lxml import html

import aap_gateway_api.views as gateway_views


def get_view_classes_with_deprecation_messages():
    """Return Gateway views that define a deprecation message."""
    for module_info in pkgutil.walk_packages(gateway_views.__path__, f"{gateway_views.__name__}."):
        module = importlib.import_module(module_info.name)
        for _, view_class in inspect.getmembers(module, inspect.isclass):
            if view_class.__module__ == module.__name__ and "deprecated_message" in view_class.__dict__:
                yield view_class


def get_deprecation_messages(view_class):
    """Return named collection and detail messages for a view, without duplicates."""
    view = view_class()
    lookup_url_kwarg = getattr(view, "lookup_url_kwarg", None) or getattr(view, "lookup_field", "pk")
    messages = set()

    for route_type, kwargs in (("collection", {}), ("detail", {lookup_url_kwarg: 1})):
        view.kwargs = kwargs
        message = view.deprecated_message
        if message:
            message = str(message)
            if message in messages:
                continue
            messages.add(message)
            yield route_type, message


def collect_deprecation_messages():
    """Build pytest parameters for every Gateway deprecation message."""
    for view_class in get_view_classes_with_deprecation_messages():
        view_name = f"{view_class.__module__}.{view_class.__name__}"
        for route_type, message in get_deprecation_messages(view_class):
            yield pytest.param(message, id=f"{view_name}[{route_type}]")


@pytest.mark.parametrize("message", list(collect_deprecation_messages()))
def test_deprecation_messages_are_valid_html(message):
    """Developer-authored deprecation messages must be valid HTML fragments."""
    parser = html.HTMLParser(recover=False)

    html.fragments_fromstring(message, parser=parser)

    assert not parser.error_log, f"Invalid deprecation message HTML: {parser.error_log}"
