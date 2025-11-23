# Create a one-off file create_rag_db.py
import os
import psycopg2
from psycopg2 import sql

dsn = os.environ.get("PG_DSN", "postgresql://postgres:postgres@localhost:5432/postgres")
print("Using admin DSN:", dsn)
parsed = psycopg2.connect(dsn)
parsed.autocommit = True
cur = parsed.cursor()
dbname = "rag_db"
try:
    cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    print(f"Database {dbname} created.")
except Exception as e:
    if "already exists" in str(e):
        print(f"Database {dbname} already exists.")
    else:
        print("Create DB error:", e)
cur.close()
parsed.close()
