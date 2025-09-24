"""
Custom cache backends for testing that provide proper worker isolation.
"""

import os

from django.core.cache.backends.redis import RedisCache


class WorkerIsolatedRedisCache(RedisCache):
    """
    Redis cache backend that provides worker isolation for parallel test execution.

    This backend ensures that cache.clear() only clears keys belonging to the current
    worker, preventing parallel test workers from interfering with each other.
    """

    def __init__(self, server, params):
        super().__init__(server, params)
        # Set worker-specific key prefix
        worker_id = os.environ.get("PYTEST_XDIST_WORKER", "main")
        original_prefix = params.get('KEY_PREFIX', '')
        self.key_prefix = f"{original_prefix}worker_{worker_id}_"

    def clear(self):
        """
        Clear only keys belonging to this worker's prefix.
        This prevents parallel test workers from interfering with each other.
        """
        # Get the client through the _cache attribute (which is the RedisCacheClient)
        client = self._cache.get_client(None, write=True)

        # Get all keys with our worker prefix
        pattern = f"{self.key_prefix}*"
        keys = client.keys(pattern)

        if keys:
            # Delete only keys with our prefix
            client.delete(*keys)
            return True
        return False
