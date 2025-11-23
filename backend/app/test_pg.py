import os
import psycopg2

dsn = os.environ.get("PG_DSN", "postgresql://postgres:postgres@localhost:5432/postgres")
print("Using PG_DSN:", dsn)

try:
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute("SELECT version();")
    print("Postgres version:", cur.fetchone())
    cur.close()
    conn.close()
    print("Postgres connection: OK")
except Exception as e:
    print("Postgres connection: FAILED")
    print(e)
