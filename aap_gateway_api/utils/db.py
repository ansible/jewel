import logging
from multiprocessing import Pool
from multiprocessing.context import TimeoutError

from django.db import DatabaseError, connections

logger = logging.getLogger("aap_gateway_api.utils.db")


def get_db_connection_status(db_name, timeout):
    """
    Attempts to connect to the DB in a terminable thread and returns at
    specified timeout (even if it's shorter than DB connection timeout).
    Returns True if successful.
    Logs and raises TimeoutError for timeout or DatabaseError for other problems.
    """
    try:
        with Pool(processes=1) as p:
            result = p.map_async(_try_connection, [db_name]).get(timeout=timeout)[0]
            return result
    except (DatabaseError, TimeoutError) as e:
        logger.error(f"Failed to connect to DB! {type(e).__name__}")
        raise
    finally:
        p.terminate()
        p.close()


def _try_connection(db_name):
    db_conn = connections.create_connection(db_name)
    c = db_conn.cursor()
    c.execute('SELECT 1')
    return True
