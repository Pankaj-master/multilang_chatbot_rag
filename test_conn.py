import os
import psycopg2
from dotenv import load_dotenv
load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL') or "postgresql://postgres:postgres@localhost:5432/ragdb"
try:
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT version();")
    print("Connected — Postgres version:", cur.fetchone())
    cur.close()
    conn.close()
except Exception as e:
    print("Connection failed:", e)
