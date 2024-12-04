from flags import conditions
from flags.state import flag_enabled


@conditions.register('feature')
def feature_condition(flag, request=None, **kwargs):
    """Condition checking if another feature flag is enabled.

    Args:
        flag: Name of the feature flag to check
        request: Django request object
        **kwargs: Additional condition arguments
    """
    return flag_enabled(flag, request=request)
