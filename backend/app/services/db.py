# backend/app/services/db.py
"""
Async Postgres helper for the RAG service.

Provides:
- async init/close pool
- simple query helpers used by retriever / ingestion / admin endpoints
- fast retrieval of chunk text snippets and document metadata

This module prefers `asyncpg` (async). If `asyncpg` is not available it falls back to
a synchronous `psycopg2` interface wrapped in threads so callers can still use it.
"""

import os
import logging
import asyncio
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("rag_app.db")

PG_DSN = os.getenv("PG_DSN") or os.getenv("DATABASE_URL") or "postgresql://postgres:postgres@localhost:5432/ragdb"

# Try asyncpg first
_try_asyncpg = True
try:
    import asyncpg  # type: ignore
except Exception:
    _try_asyncpg = False
    logger.warning("asyncpg not available; falling back to threaded psycopg2 (less efficient).")

# Threaded psycopg2 fallback
_try_psycopg2 = True
try:
    import psycopg2
    import psycopg2.extras
    from concurrent.futures import ThreadPoolExecutor
except Exception:
    _try_psycopg2 = False
    logger.debug("psycopg2 not available as fallback for DB synchronous operations.")


# -------------------------
# AsyncPG pool (preferred)
# -------------------------
_db_pool: Optional["asyncpg.pool.Pool"] = None  # type: ignore


async def init_db_pool(min_size: int = 1, max_size: int = 10, timeout: int = 60) -> None:
    """
    Initialize asyncpg connection pool. Call at application startup.
    """
    global _db_pool
    if _db_pool is not None:
        return
    if not _try_asyncpg:
        logger.warning("asyncpg not installed; skipping async pool initialization.")
        return
    try:
        logger.info("Initializing asyncpg pool to %s", PG_DSN)
        _db_pool = await asyncpg.create_pool(dsn=PG_DSN, min_size=min_size, max_size=max_size, command_timeout=timeout)
        logger.info("asyncpg pool initialized")
    except Exception as e:
        logger.exception("Failed to initialize asyncpg pool: %s", e)
        _db_pool = None


async def close_db_pool() -> None:
    """
    Close asyncpg pool gracefully. Call at shutdown.
    """
    global _db_pool
    if _db_pool:
        try:
            await _db_pool.close()
            logger.info("Closed asyncpg pool")
        except Exception as e:
            logger.exception("Error closing asyncpg pool: %s", e)
        _db_pool = None


# -------------------------
# Threaded psycopg2 fallback
# -------------------------
_thread_executor: Optional[ThreadPoolExecutor] = None
_psyc_pooled_conn = None


def _ensure_thread_executor(max_workers: int = 4):
    global _thread_executor
    if _thread_executor is None:
        _thread_executor = ThreadPoolExecutor(max_workers=max_workers)


def _psycoget_conn():
    """
    Get a new psycopg2 connection (not pooled). Caller must close.
    """
    return psycopg2.connect(PG_DSN)


# -------------------------
# Utility helpers
# -------------------------

async def fetch_rows(query: str, *args) -> List[Dict[str, Any]]:
    """
    Fetch rows as list of dicts. Uses asyncpg if available; otherwise runs in threadpool.
    """
    if _try_asyncpg and _db_pool:
        try:
            async with _db_pool.acquire() as conn:
                rows = await conn.fetch(query, *args)
                # convert Record -> dict
                return [dict(r) for r in rows]
        except Exception as e:
            logger.exception("asyncpg fetch_rows failed: %s", e)
            raise
    # fallback to psycopg2 in thread
    if not _try_psycopg2:
        raise RuntimeError("No DB client available (asyncpg or psycopg2).")
    _ensure_thread_executor()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_thread_executor, _fetch_rows_sync, query, args)


def _fetch_rows_sync(query: str, args: Sequence) -> List[Dict[str, Any]]:
    conn = None
    try:
        conn = psycopg2.connect(PG_DSN)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(query, args)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        if conn:
            conn.close()


async def fetch_one(query: str, *args) -> Optional[Dict[str, Any]]:
    """
    Fetch a single row or None.
    """
    rows = await fetch_rows(query, *args)
    return rows[0] if rows else None


async def execute(query: str, *args) -> None:
    """
    Execute a statement (INSERT/UPDATE/DELETE). Uses asyncpg or threaded psycopg2.
    """
    if _try_asyncpg and _db_pool:
        try:
            async with _db_pool.acquire() as conn:
                await conn.execute(query, *args)
                return
        except Exception as e:
            logger.exception("asyncpg execute failed: %s", e)
            raise
    if not _try_psycopg2:
        raise RuntimeError("No DB client available (asyncpg or psycopg2).")
    _ensure_thread_executor()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_thread_executor, _execute_sync, query, args)


def _execute_sync(query: str, args: Sequence) -> None:
    conn = None
    try:
        conn = psycopg2.connect(PG_DSN)
        cur = conn.cursor()
        cur.execute(query, args)
        conn.commit()
    finally:
        if conn:
            conn.close()


# -------------------------
# Domain-specific helpers
# -------------------------

async def get_chunk_texts_by_ids(chunk_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Return list of {"chunk_id","doc_id","text_snippet","page","chunk_index"} for the provided chunk_ids.
    """
    if not chunk_ids:
        return []
    # Use IN clause safely by passing args to asyncpg / psycopg2 (works with both)
    placeholders = ", ".join([f"${i+1}" for i in range(len(chunk_ids))]) if (_try_asyncpg and _db_pool) else ", ".join(["%s"] * len(chunk_ids))
    query = f"SELECT chunk_id, doc_id, text_snippet, page, chunk_index FROM kb_chunks WHERE chunk_id IN ({placeholders})"
    return await fetch_rows(query, *chunk_ids)


async def get_top_chunks_for_doc(doc_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Return top N chunks (by created_at) for a given document.
    """
    query = "SELECT chunk_id, doc_id, text_snippet, page, chunk_index FROM kb_chunks WHERE doc_id = $1 ORDER BY created_at DESC LIMIT $2" if (_try_asyncpg and _db_pool) else "SELECT chunk_id, doc_id, text_snippet, page, chunk_index FROM kb_chunks WHERE doc_id = %s ORDER BY created_at DESC LIMIT %s"
    return await fetch_rows(query, doc_id, limit)


async def list_documents(limit: int = 50) -> List[Dict[str, Any]]:
    """
    List recent documents.
    """
    query = "SELECT doc_id, source_type, source_path, title, uploaded_at FROM kb_documents ORDER BY uploaded_at DESC LIMIT $1" if (_try_asyncpg and _db_pool) else "SELECT doc_id, source_type, source_path, title, uploaded_at FROM kb_documents ORDER BY uploaded_at DESC LIMIT %s"
    return await fetch_rows(query, limit)


async def get_document(doc_id: str) -> Optional[Dict[str, Any]]:
    query = "SELECT doc_id, source_type, source_path, title, uploaded_at FROM kb_documents WHERE doc_id = $1" if (_try_asyncpg and _db_pool) else "SELECT doc_id, source_type, source_path, title, uploaded_at FROM kb_documents WHERE doc_id = %s"
    return await fetch_one(query, doc_id)


# -------------------------
# Startup / shutdown helpers for FastAPI
# -------------------------

async def startup():
    """
    Call this in FastAPI startup event to initialize the pool.
    """
    await init_db_pool()


async def shutdown():
    """
    Call this in FastAPI shutdown event to close pool.
    """
    await close_db_pool()
