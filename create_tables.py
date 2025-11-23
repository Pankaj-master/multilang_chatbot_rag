#!/usr/bin/env python3
"""
create_tables.py

Create Postgres tables required by the RAG app.

Usage:
  PG_DSN=postgresql://user:pass@host:5432/dbname python create_tables.py
"""

import os
import sys
import logging
import psycopg2
from psycopg2 import sql

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("create_tables")

PG_DSN = os.getenv("PG_DSN") or os.getenv("DATABASE_URL") or "postgresql://postgres:postgres@localhost:5432/ragdb"

# SQL statements to create tables and indexes
CREATE_DOCS = """
CREATE TABLE IF NOT EXISTS kb_documents (
    doc_id TEXT PRIMARY KEY,
    source_type TEXT,
    source_path TEXT,
    title TEXT,
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    metadata JSONB
);
"""

CREATE_CHUNKS = """
CREATE TABLE IF NOT EXISTS kb_chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT REFERENCES kb_documents(doc_id) ON DELETE CASCADE,
    page INTEGER,
    row_index INTEGER,
    chunk_index INTEGER,
    text_snippet TEXT,
    language TEXT,
    char_start INTEGER,
    char_end INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);
"""

ADD_TSVECTOR_COLUMN = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='kb_chunks' AND column_name='text_search_vector'
    ) THEN
        ALTER TABLE kb_chunks ADD COLUMN text_search_vector tsvector;
    END IF;
END$$;
"""

UPDATE_TSVECTOR_TRIGGER_FN = """
CREATE OR REPLACE FUNCTION kb_chunks_text_search_trigger() RETURNS trigger AS $$
begin
  new.text_search_vector :=
    setweight(to_tsvector('english', coalesce(new.text_snippet,'')), 'A');
  return new;
end
$$ LANGUAGE plpgsql;
"""

CREATE_TSVECTOR_TRIGGER = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'kb_chunks_tsvector_update'
    ) THEN
        CREATE TRIGGER kb_chunks_tsvector_update
        BEFORE INSERT OR UPDATE ON kb_chunks
        FOR EACH ROW EXECUTE PROCEDURE kb_chunks_text_search_trigger();
    END IF;
END$$;
"""

CREATE_INDEXES = """
-- Basic indexes
CREATE INDEX IF NOT EXISTS idx_kb_chunks_doc_id ON kb_chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_chunk_index ON kb_chunks(chunk_index);
CREATE INDEX IF NOT EXISTS idx_kb_chunks_language ON kb_chunks(language);

-- GIN index for full-text search on text_search_vector
CREATE INDEX IF NOT EXISTS idx_kb_chunks_text_search ON kb_chunks USING GIN (text_search_vector);

-- Optional trigram index on text_snippet to support ILIKE / fuzzy search
-- Requires pg_trgm extension; will attempt to create extension if allowed
"""

BACKFILL_TSVECTOR = """
UPDATE kb_chunks SET text_search_vector = setweight(to_tsvector('english', coalesce(text_snippet,'')), 'A') WHERE text_search_vector IS NULL;
"""

CREATE_PG_TRGM_EXTENSION = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
        CREATE EXTENSION pg_trgm;
    END IF;
END$$;
"""

CREATE_TRGM_INDEX = """
CREATE INDEX IF NOT EXISTS idx_kb_chunks_text_trgm ON kb_chunks USING GIN (text_snippet gin_trgm_ops);
"""

def run_sql(conn, sql_text):
    with conn.cursor() as cur:
        cur.execute(sql_text)
    conn.commit()


def main():
    logger.info("Connecting to Postgres: %s", PG_DSN)
    try:
        conn = psycopg2.connect(PG_DSN)
    except Exception as e:
        logger.exception("Failed to connect to Postgres. Set PG_DSN or DATABASE_URL env var. Error: %s", e)
        sys.exit(1)

    try:
        logger.info("Creating kb_documents table...")
        run_sql(conn, CREATE_DOCS)

        logger.info("Creating kb_chunks table...")
        run_sql(conn, CREATE_CHUNKS)

        logger.info("Adding text_search_vector column if missing...")
        run_sql(conn, ADD_TSVECTOR_COLUMN)

        logger.info("Creating tsvector trigger function...")
        run_sql(conn, UPDATE_TSVECTOR_TRIGGER_FN)

        logger.info("Creating tsvector trigger...")
        run_sql(conn, CREATE_TSVECTOR_TRIGGER)

        logger.info("Creating basic indexes...")
        run_sql(conn, CREATE_INDEXES)

        # Try to create pg_trgm extension and trigram index (best-effort; may require superuser)
        try:
            logger.info("Ensuring pg_trgm extension exists (if permitted)...")
            run_sql(conn, CREATE_PG_TRGM_EXTENSION)
            logger.info("Creating trigram index (if permitted)...")
            run_sql(conn, CREATE_TRGM_INDEX)
        except Exception as e:
            logger.warning("pg_trgm / trigram index creation failed or not permitted: %s", e)

        logger.info("Backfilling text_search_vector for existing rows (if any)...")
        run_sql(conn, BACKFILL_TSVECTOR)

        logger.info("All done. Tables are ready.")
    except Exception as e:
        logger.exception("Error running DDL: %s", e)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
