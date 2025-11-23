# backend/app/ingestion/upsert.py
"""
Upsert helper for ingestion pipeline.

Functions:
  - upsert_chunks(doc_id, chunks_meta, embeddings, docs_meta) -> dict

Notes:
  - chunks_meta: list of dicts. Each dict should have keys like:
        "chunk_index": int,
        "text": str,
        optional "page"/"row_index"/"char_start"/"char_end"
  - embeddings: list of vectors aligned with chunks_meta (or []/None)
  - docs_meta: dict with doc metadata (source_type, path, title, metadata...)

Behavior:
  - Writes/updates kb_documents
  - Deletes existing kb_chunks for this doc_id and inserts provided chunks
  - If Pinecone configured, upserts vectors (ids match chunk_id)
"""

import os
import hashlib
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger("rag_app.upsert")

PG_DSN = os.getenv("PG_DSN") or os.getenv("DATABASE_URL")
# Pinecone config
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_ENV = os.getenv("PINECONE_ENV")
PINECONE_INDEX = os.getenv("PINECONE_INDEX", "kb-index")

# Try psycopg2 for sync DB writes
_try_psycopg2 = False
try:
    import psycopg2
    import psycopg2.extras
    _try_psycopg2 = True
except Exception:
    _try_psycopg2 = False
    logger.warning("psycopg2 not available: DB upsert will be disabled.")

# Try Pinecone
_pinecone_index = None
_try_pinecone = False
if PINECONE_API_KEY and PINECONE_ENV:
    try:
        import pinecone  # type: ignore
        pinecone.init(api_key=PINECONE_API_KEY, environment=PINECONE_ENV)
        if PINECONE_INDEX in pinecone.list_indexes():
            _pinecone_index = pinecone.Index(PINECONE_INDEX)
            _try_pinecone = True
            logger.info("Pinecone index connected: %s", PINECONE_INDEX)
        else:
            logger.warning("Pinecone index %s not found. Pinecone upserts will be skipped.", PINECONE_INDEX)
            _try_pinecone = False
    except Exception as e:
        logger.exception("Failed to initialize Pinecone client: %s", e)
        _try_pinecone = False
else:
    logger.debug("Pinecone not configured; skipping vector upserts.")


def _compute_chunk_id(doc_id: str, chunk_index: int) -> str:
    """
    Stable chunk id: sha1(doc_id | chunk_index)
    """
    s = f"{doc_id}|{chunk_index}"
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _get_pg_conn():
    if not _try_psycopg2:
        raise RuntimeError("psycopg2 not available or not installed.")
    if not PG_DSN:
        raise RuntimeError("PG_DSN / DATABASE_URL not set.")
    return psycopg2.connect(PG_DSN)


def _upsert_document(conn, doc_id: str, docs_meta: Dict[str, Any]):
    """
    Insert or update kb_documents row.
    """
    sql = """
    INSERT INTO kb_documents (doc_id, source_type, source_path, title, uploaded_at, metadata)
    VALUES (%s, %s, %s, %s, now(), %s)
    ON CONFLICT (doc_id) DO UPDATE
      SET source_type = EXCLUDED.source_type,
          source_path = EXCLUDED.source_path,
          title = EXCLUDED.title,
          metadata = EXCLUDED.metadata,
          uploaded_at = now()
    """
    cur = conn.cursor()
    metadata = docs_meta.get("metadata") if isinstance(docs_meta.get("metadata"), dict) else docs_meta
    params = (doc_id, docs_meta.get("source_type"), docs_meta.get("path") or docs_meta.get("source_path"), docs_meta.get("title"), psycopg2.extras.Json(metadata))
    cur.execute(sql, params)


def _delete_existing_chunks(conn, doc_id: str):
    cur = conn.cursor()
    cur.execute("DELETE FROM kb_chunks WHERE doc_id = %s", (doc_id,))


def _insert_chunks(conn, doc_id: str, chunks_meta: List[Dict[str, Any]]):
    """
    Bulk insert chunks into kb_chunks.
    Each row: chunk_id, doc_id, page, row_index, chunk_index, text_snippet, language, char_start, char_end
    """
    sql = """
    INSERT INTO kb_chunks (chunk_id, doc_id, page, row_index, chunk_index, text_snippet, language, char_start, char_end, created_at)
    VALUES %s
    """
    values = []
    for c in chunks_meta:
        chunk_index = int(c.get("chunk_index", 0))
        chunk_id = _compute_chunk_id(doc_id, chunk_index)
        page = c.get("page")
        row_index = c.get("row_index")
        text = c.get("text") or c.get("text_snippet") or ""
        lang = c.get("language") or c.get("lang") or None
        char_start = c.get("char_start")
        char_end = c.get("char_end")
        values.append((chunk_id, doc_id, page, row_index, chunk_index, text, lang, char_start, char_end))
    # Use execute_values for fast bulk insert
    try:
        psycopg2.extras.execute_values(conn.cursor(), sql, values, template=None, page_size=100)
    except Exception:
        # fallback to row-by-row
        cur = conn.cursor()
        for v in values:
            cur.execute("INSERT INTO kb_chunks (chunk_id, doc_id, page, row_index, chunk_index, text_snippet, language, char_start, char_end, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s, now())", v)


def _prepare_pinecone_items(doc_id: str, chunks_meta: List[Dict[str, Any]], embeddings: Optional[List[List[float]]]):
    """
    Prepare list of (id, vector, metadata) for Pinecone upsert.
    metadata includes doc_id, chunk_index, source_path, text_snippet (truncated), page etc.
    """
    items = []
    for idx, c in enumerate(chunks_meta):
        chunk_index = int(c.get("chunk_index", idx))
        chunk_id = _compute_chunk_id(doc_id, chunk_index)
        vec = None
        if embeddings and idx < len(embeddings):
            vec = embeddings[idx]
        # prepare metadata (keep text snippet short to avoid large metadata)
        text = c.get("text") or ""
        meta = {
            "doc_id": doc_id,
            "chunk_index": chunk_index,
            "page": c.get("page"),
            "row_index": c.get("row_index"),
        }
        # include a short snippet for debugging/citation (truncate to 500 chars)
        meta["text_snippet"] = (text[:500] + "...") if len(text) > 500 else text
        items.append((chunk_id, vec, meta))
    return items


def upsert_chunks(doc_id: str, chunks_meta: List[Dict[str, Any]], embeddings: Optional[List[List[float]]] = None, docs_meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Upsert document & chunks into Postgres and vectors into Pinecone (if configured).

    Returns dict:
      {
        "ok": True,
        "doc_id": doc_id,
        "chunks_written": N,
        "pinecone_upserted": M or None,
        "errors": [...]
      }
    """
    if docs_meta is None:
        docs_meta = {}

    summary: Dict[str, Any] = {"ok": False, "doc_id": doc_id, "chunks_written": 0, "pinecone_upserted": None, "errors": []}

    # 1) Upsert into Postgres (if available)
    if _try_psycopg2 and PG_DSN:
        conn = None
        try:
            conn = _get_pg_conn()
            conn.autocommit = False
            _upsert_document(conn, doc_id, docs_meta)
            _delete_existing_chunks(conn, doc_id)
            if chunks_meta:
                _insert_chunks(conn, doc_id, chunks_meta)
            conn.commit()
            summary["chunks_written"] = len(chunks_meta)
        except Exception as e:
            if conn:
                conn.rollback()
            logger.exception("Postgres upsert failed for doc_id=%s: %s", doc_id, e)
            summary["errors"].append(f"postgres:{str(e)}")
            # do not fail completely; continue to pinecone attempt if possible
        finally:
            if conn:
                conn.close()
    else:
        logger.warning("Postgres not configured or psycopg2 missing; skipping DB upsert.")
        summary["errors"].append("postgres:disabled")

    # 2) Upsert vectors to Pinecone (if available)
    if _try_pinecone and _pinecone_index is not None:
        try:
            items = _prepare_pinecone_items(doc_id, chunks_meta, embeddings)
            # Filter items with vector present
            to_upsert = []
            for cid, vec, meta in items:
                if vec is None:
                    # skip items without vectors
                    continue
                to_upsert.append({"id": cid, "values": vec, "metadata": meta})
            if to_upsert:
                # Pinecone upsert in batches (100 by default)
                batch_size = 100
                upserted = 0
                for i in range(0, len(to_upsert), batch_size):
                    batch = to_upsert[i:i+batch_size]
                    res = _pinecone_index.upsert(vectors=batch)
                    # res may be a dict or object; try to capture info
                    upserted += len(batch)
                summary["pinecone_upserted"] = upserted
            else:
                summary["pinecone_upserted"] = 0
        except Exception as e:
            logger.exception("Pinecone upsert failed for doc_id=%s: %s", doc_id, e)
            summary["errors"].append(f"pinecone:{str(e)}")
    else:
        logger.debug("Pinecone not configured; skipping vector upsert.")
        summary["pinecone_upserted"] = None
        summary["errors"].append("pinecone:disabled")

    # success if at least DB wrote chunks or pinecone upsert succeeded
    summary["ok"] = (summary.get("chunks_written", 0) > 0) or (summary.get("pinecone_upserted") not in (None, 0))
    return summary
