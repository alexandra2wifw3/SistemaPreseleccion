import psycopg2
import psycopg2.extras
import psycopg2.pool
import os

_pool = None

def get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=os.getenv("DATABASE_URL"),
            cursor_factory=psycopg2.extras.RealDictCursor
        )
    return _pool

def get_db():
    """Obtiene una conexión del pool."""
    return get_pool().getconn()

def release_db(conn):
    """Devuelve la conexión al pool en vez de cerrarla."""
    if conn:
        get_pool().putconn(conn)