#!/usr/bin/env python3
"""
create_db.py

Creates a new PostgreSQL database if it does not already exist.

Requires:
  PG_ADMIN_DSN      -> e.g. "postgresql://postgres:postgres@localhost:5432/postgres"
  PG_DATABASE_NAME  -> e.g. "rag_db"

Usage (PowerShell):
  $env:PG_ADMIN_DSN="postgresql://postgres:postgres@localhost:5432/postgres"
  $env:PG_DATABASE_NAME="rag_db"
  python create_db.py
"""

import os
import sys
import logging
import psycopg2

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("create_db")

PG_ADMIN_DSN = os.getenv("PG_ADMIN_DSN")
DB_NAME = os.getenv("PG_DATABASE_NAME")

def main():
    if not PG_ADMIN_DSN:
        logger.error("PG_ADMIN_DSN not set. Example:")
        logger.error('  $env:PG_ADMIN_DSN="postgresql://postgres:postgres@localhost:5432/postgres"')
        sys.exit(1)

    if not DB_NAME:
        logger.error("PG_DATABASE_NAME not set. Example:")
        logger.error('  $env:PG_DATABASE_NAME="rag_db"')
        sys.exit(1)

    logger.info(f"Connecting to admin database: {PG_ADMIN_DSN}")
    try:
        conn = psycopg2.connect(PG_ADMIN_DSN)
        conn.autocommit = True
    except Exception as e:
        logger.exception("Failed to connect using PG_ADMIN_DSN: %s", e)
        sys.exit(1)

    try:
        with conn.cursor() as cur:
            # Check if database already exists
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (DB_NAME,))
            exists = cur.fetchone() is not None

            if exists:
                logger.info(f"Database '{DB_NAME}' already exists. Nothing to do.")
            else:
                logger.info(f"Database '{DB_NAME}' does not exist. Creating...")
                cur.execute(f"CREATE DATABASE {DB_NAME};")
                logger.info(f"Database '{DB_NAME}' created successfully!")

    except Exception as e:
        logger.exception("Error while creating database: %s", e)
        sys.exit(1)
    finally:
        conn.close()

    logger.info("Done.")

if __name__ == "__main__":
    main()
