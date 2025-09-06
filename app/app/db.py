import os
from psycopg_pool import ConnectionPool

DB_HOST = os.getenv("DB_HOST", "postgres")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_USER = os.getenv("DB_USER", "geo")
DB_PASSWORD = os.getenv("DB_PASSWORD", "change-me")
DB_NAME_LARGEST = os.getenv("DB_NAME_LARGEST", "geodb_largest")

_pools = {}
def get_pool():
    key = (DB_HOST, DB_PORT, DB_USER, DB_NAME_LARGEST)
    if key not in _pools:
        conninfo = f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME_LARGEST} user={DB_USER} password={DB_PASSWORD}"
        _pools[key] = ConnectionPool(conninfo=conninfo, min_size=1, max_size=10, kwargs={"autocommit": True})
    return _pools[key]
