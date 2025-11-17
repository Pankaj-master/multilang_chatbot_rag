# create_tables.py
import os
import psycopg2
from dotenv import load_dotenv
load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL') or "postgresql://postgres:postgres@localhost:5432/ragdb"

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS food_items (
  id SERIAL PRIMARY KEY,
  name TEXT,
  category TEXT,
  nutrients JSONB,
  dosha_properties JSONB,
  notes TEXT,
  raw_row JSONB,
  created_at TIMESTAMP DEFAULT now()
);
""")
print("food_items table created (or already exists)")

cur.execute("""
CREATE TABLE IF NOT EXISTS sources (
  source_id TEXT PRIMARY KEY,
  title TEXT,
  type TEXT,
  language TEXT,
  author TEXT,
  publisher TEXT,
  year TEXT,
  source_url TEXT,
  license TEXT,
  notes TEXT,
  created_at TIMESTAMP DEFAULT now()
);
""")
print("sources table created (or already exists)")

cur.close()
conn.close()
