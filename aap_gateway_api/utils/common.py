__all__ = ['get_api_version']


def get_api_version():
    """
    Return version as reported by setuptools.
    """
    try:
        from importlib.metadata import version
        return version('aap_gateway_api')
    except Exception:
        import os

        current_dir = os.path.dirname(os.path.abspath(__file__))
        version_file = os.path.join(current_dir, '..', 'VERSION')

        if os.path.exists(version_file):
            with open(version_file, 'r') as file:
                return file.read().strip()
        else:
            return "Unknown"
