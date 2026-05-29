from ansible_base.lib.cache.tasks import clear_cache
from dispatcherd.publish import task


@task(queue='gateway_broadcast', timeout=600)
def clear_gateway_cache(cache_keys):
    clear_cache(cache_keys)
