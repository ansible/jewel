import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from django.db import connections
from django.db.utils import OperationalError

logger = logging.getLogger("aap.aap_gateway_api.utils.db")


def get_db_connection_status(db_name, timeout):
    """
    Attempts to connect to the DB in a separate thread and returns after
    specified timeout (even if it's shorter than DB connection timeout).
    Returns True if successful.
    Logs and raises TimeoutError for timeout or OperationalError for other problems.
    """
    # Not using "with ...:", it would wait for thread to finish even after timeout
    ex = ThreadPoolExecutor(thread_name_prefix="db_status")
    start_time = datetime.now()
    future = ex.submit(_check_db, db_name)
    try:
        result = future.result(timeout=timeout)
        return result
    except TimeoutError:
        elapsed_time = datetime.now() - start_time
        logger.warning(f"Thread checking status of database did not finish in time, ran for {elapsed_time.total_seconds()} seconds, abandoning the thread!")
        raise
    finally:
        # shutting down and not waiting for the thread
        ex.shutdown(wait=False)


def _check_db(db_name):
    try:
        c = connections[db_name].cursor()
        c.execute("SELECT 1;")
        c.close()
        return True
    except OperationalError as e:
        logger.error(f"Failed to connect to DB! {type(e).__name__} ")
        raise
