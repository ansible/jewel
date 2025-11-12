"""Pytest configuration for script tests"""


# Disable Django for these tests
def pytest_configure(config):
    """Configure pytest to not use Django for these tests"""
    # Remove django plugin if it was loaded
    if config.pluginmanager.hasplugin("django"):
        config.pluginmanager.unregister(name="django")
