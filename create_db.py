import os
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL') or "postgresql://postgres:postgres@localhost:5432/postgres"

# connect to existing default 'postgres' DB to run CREATE DATABASE
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()
try:
    cur.execute("CREATE DATABASE ragdb;")
    print("Created database ragdb")
except Exception as e:
    print("Create DB error (may already exist):", e)
cur.close()
conn.close()
