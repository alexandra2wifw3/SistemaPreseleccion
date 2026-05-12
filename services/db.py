import psycopg2
import psycopg2.extras
import os

def get_db():
    """Retorna una conexión a NeonDB con cursor tipo diccionario."""
    conn = psycopg2.connect(
        os.getenv("DATABASE_URL"),
        cursor_factory=psycopg2.extras.RealDictCursor
    )
    return conn