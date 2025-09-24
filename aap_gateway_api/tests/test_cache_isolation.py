"""
Test cache isolation between parallel test workers.
"""

import os

import pytest


def test_cache_isolation_basic(isolated_cache):
    """Test that cache isolation works for basic operations."""
    # Set a value in this worker's cache
    isolated_cache.set('test_key', 'test_value')

    # Verify we can retrieve it
    assert isolated_cache.get('test_key') == 'test_value'

    # Clear the cache - should only clear this worker's entries
    isolated_cache.clear()

    # Verify it's cleared
    assert isolated_cache.get('test_key') is None


def test_cache_isolation_worker_prefix(isolated_cache):
    """Test that different workers get different key prefixes."""
    # Get the current worker ID
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "main")

    # Check that the cache has a worker-specific prefix
    expected_prefix = f"worker_{worker_id}_"
    assert expected_prefix in isolated_cache.key_prefix

    # Set a key and verify it gets the worker prefix
    isolated_cache.set('prefix_test', 'value')

    # The actual Redis key should include the worker prefix
    client = isolated_cache._cache.get_client(None)
    pattern = f"{isolated_cache.key_prefix}*"
    keys = client.keys(pattern)

    # Should have at least one key with our worker prefix
    assert len(keys) > 0
    assert all(key.decode().startswith(isolated_cache.key_prefix) for key in keys)


def test_cache_clear_only_affects_worker(isolated_cache):
    """Test that cache.clear() only clears the current worker's keys."""
    # This test simulates what would happen if multiple workers were running
    # In practice, each worker would have its own cache instance with different prefixes

    # Set a key in this worker's cache
    isolated_cache.set('worker_specific_key', 'worker_value')

    # Verify it exists
    assert isolated_cache.get('worker_specific_key') == 'worker_value'

    # Simulate another worker's key by directly setting it in Redis
    # (This wouldn't normally happen, but tests the isolation)
    client = isolated_cache._cache.get_client(None)
    other_worker_key = 'worker_other_test_key'
    client.set(other_worker_key, 'other_value')

    # Verify the other key exists
    assert client.get(other_worker_key) == b'other_value'

    # Clear this worker's cache
    isolated_cache.clear()

    # This worker's key should be gone
    assert isolated_cache.get('worker_specific_key') is None

    # But the other key should still exist (since it doesn't have our worker prefix)
    assert client.get(other_worker_key) == b'other_value'

    # Cleanup the other key
    client.delete(other_worker_key)


@pytest.mark.parametrize(
    "cache_key,cache_value",
    [
        ("simple_key", "simple_value"),
        ("complex:key:with:colons", {"dict": "value"}),
        ("unicode_key_ñoño", "unicode_value_ñoño"),
    ],
)
def test_cache_isolation_various_key_types(isolated_cache, cache_key, cache_value):
    """Test cache isolation with various key and value types."""
    # Set the value
    isolated_cache.set(cache_key, cache_value)

    # Verify we can retrieve it
    assert isolated_cache.get(cache_key) == cache_value

    # Clear and verify it's gone
    isolated_cache.clear()
    assert isolated_cache.get(cache_key) is None
