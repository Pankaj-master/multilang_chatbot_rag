# backend/app/check_chunks.py
import os, psycopg2
dsn = os.environ.get("PG_DSN", "postgresql://postgres:postgres@localhost:5432/rag_db")
print("Using DSN:", dsn)
conn = psycopg2.connect(dsn)
cur = conn.cursor()
cur.execute("SELECT count(*) FROM kb_chunks;")
print("kb_chunks rows:", cur.fetchone()[0])
cur.close()
conn.close()
