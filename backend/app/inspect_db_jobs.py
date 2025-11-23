# backend/app/inspect_db_jobs.py
import os, psycopg2
dsn = os.environ.get("PG_DSN", "postgresql://postgres:postgres@localhost:5432/rag_db")
print("Using DSN:", dsn)
conn = psycopg2.connect(dsn)
cur = conn.cursor()

print("\n--- list tables (public schema) ---")
cur.execute("""
SELECT tablename FROM pg_catalog.pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;
""")
for r in cur.fetchall():
    print(r[0])

def safe_select_count(table):
    try:
        cur.execute(f"SELECT count(*) FROM {table};")
        print(f"{table} rows:", cur.fetchone()[0])
    except Exception as e:
        print(f"{table}: error ->", e)

print("\n--- counts ---")
for t in ("kb_documents","kb_chunks","kb_documents_meta","ingest_jobs","ingest_queue","jobs","task_queue"):
    safe_select_count(t)

print("\n--- recent kb_documents (limit 10) ---")
try:
    cur.execute("SELECT id, source, filename, metadata, created_at FROM kb_documents ORDER BY created_at DESC LIMIT 10;")
    for r in cur.fetchall():
        print(r)
except Exception as e:
    print("kb_documents select error:", e)

cur.close()
conn.close()
