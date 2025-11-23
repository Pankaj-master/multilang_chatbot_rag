# backend/app/services/retriever.py
"""
Hybrid retriever: semantic (Pinecone) + lexical (Postgres full-text) + reranking.

Synchronous API to match routes/chat.py usage:
    retrieved = hybrid_retrieval(query, top_k=5, language="en")

Returns list of dicts:
    {
      "chunk_id": str,
      "doc_id": str,
      "chunk_index": int,
      "text": str,
      "score": float,
      "source": "pinecone"|"lexical"
    }
"""

import os
import logging
import math
from typing import List, Dict, Optional, Tuple, Set

logger = logging.getLogger("rag_app.retriever")

# Embedding helper (sync)
try:
    from ..services.embeddings import embed_texts
except Exception:
    embed_texts = None
    logger.warning("embeddings.embed_texts not available; semantic retrieval disabled.")

# Reranker
try:
    from ..services.reranker import rerank_candidates
except Exception:
    rerank_candidates = None
    logger.warning("reranker not available; skipping reranking.")

# Pinecone client
_pinecone_index = None
try:
    import pinecone  # type: ignore
    PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
    PINECONE_ENV = os.getenv("PINECONE_ENV")
    PINECONE_INDEX = os.getenv("PINECONE_INDEX", "kb-index")
    if PINECONE_API_KEY and PINECONE_ENV:
        try:
            pinecone.init(api_key=PINECONE_API_KEY, environment=PINECONE_ENV)
            if PINECONE_INDEX in pinecone.list_indexes():
                _pinecone_index = pinecone.Index(PINECONE_INDEX)
                logger.info("Connected to Pinecone index %s", PINECONE_INDEX)
            else:
                logger.warning("Pinecone index %s not found.", PINECONE_INDEX)
        except Exception as e:
            logger.exception("Failed to init Pinecone: %s", e)
            _pinecone_index = None
    else:
        logger.debug("Pinecone credentials not set; semantic retrieval disabled.")
except Exception:
    _pinecone_index = None
    logger.debug("pinecone client import failed; semantic retrieval disabled.")

# Postgres sync helper (psycopg2)
_pg_dsn = os.getenv("PG_DSN") or os.getenv("DATABASE_URL") or "postgresql://postgres:postgres@localhost:5432/ragdb"
try:
    import psycopg2
    import psycopg2.extras
except Exception:
    psycopg2 = None
    logger.warning("psycopg2 not installed; lexical retrieval disabled.")


# -------------------------
# DB helper (sync)
# -------------------------
def _get_pg_conn():
    if not psycopg2:
        raise RuntimeError("psycopg2 is required for DB access.")
    return psycopg2.connect(_pg_dsn)


def _fetch_chunks_by_ids_sync(chunk_ids: List[str]) -> List[Dict]:
    """
    Fetch chunk rows for the provided chunk_ids (sync).
    Returns list of dicts with keys: chunk_id, doc_id, text_snippet, page, chunk_index
    """
    if not chunk_ids:
        return []
    placeholders = ", ".join(["%s"] * len(chunk_ids))
    sql = f"""
        SELECT chunk_id, doc_id, text_snippet, page, chunk_index
        FROM kb_chunks
        WHERE chunk_id IN ({placeholders})
    """
    conn = None
    try:
        conn = _get_pg_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, tuple(chunk_ids))
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.exception("DB fetch_chunks_by_ids_sync failed: %s", e)
        return []
    finally:
        if conn:
            conn.close()


def _lexical_search_sync(query: str, limit: int = 50, language: Optional[str] = None) -> List[Dict]:
    """
    Simple lexical search using Postgres full-text (plainto_tsquery).
    Returns list of dicts: chunk_id, doc_id, text_snippet, score
    """
    if not psycopg2:
        logger.debug("psycopg2 not available; lexical search skipped.")
        return []

    # If a language column exists, user can pass language to filter. We'll attempt to use it, but not required.
    lang_filter_sql = ""
    params = []
    if language:
        # assume kb_chunks.language exists; if not, the filter will fail silently and be ignored in except block
        lang_filter_sql = "AND language = %s"
        params.append(language)

    # Use plainto_tsquery for simple tokenization; tune to your locale/analyzers as needed.
    try:
        conn = _get_pg_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        # Build SQL: compute rank using ts_rank; use to_tsquery or plainto_tsquery
        sql = f"""
            SELECT chunk_id, doc_id, text_snippet, ts_rank(to_tsvector('simple', coalesce(text_snippet, '')), plainto_tsquery('simple', %s)) AS rank
            FROM kb_chunks
            WHERE coalesce(text_snippet,'') <> '' AND to_tsvector('simple', coalesce(text_snippet,'')) @@ plainto_tsquery('simple', %s)
            {lang_filter_sql}
            ORDER BY rank DESC
            LIMIT %s
        """
        params = [query, query] + params + [limit]
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
        results = []
        for r in rows:
            results.append({"chunk_id": r["chunk_id"], "doc_id": r["doc_id"], "text_snippet": r["text_snippet"], "score": float(r.get("rank", 0.0))})
        return results
    except Exception as e:
        logger.exception("Lexical search failed: %s", e)
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


# -------------------------
# Pinecone semantic query
# -------------------------
def _semantic_search_pinecone(embedding: List[float], top_k: int = 50, filter: Optional[dict] = None) -> List[Dict]:
    """
    Query Pinecone and return list of matches with minimal metadata.
    Each match: {'id': chunk_id, 'score': float, 'metadata': {...}}
    """
    if _pinecone_index is None:
        logger.debug("Pinecone index not configured.")
        return []
    try:
        # include_metadata True to get doc_id/page info stored in metadata
        res = _pinecone_index.query(vector=embedding, top_k=top_k, include_metadata=True)
        matches = res.get("matches", []) if isinstance(res, dict) else res.matches
        results = []
        for m in matches:
            meta = m.get("metadata", {}) if isinstance(m, dict) else m.metadata
            results.append({
                "chunk_id": m["id"] if isinstance(m, dict) else m.id,
                "score": float(m.get("score", 0.0) if isinstance(m, dict) else m.score),
                "metadata": meta
            })
        return results
    except Exception as e:
        logger.exception("Pinecone query failed: %s", e)
        return []


# -------------------------
# Merge & fetch texts
# -------------------------
def _merge_candidate_ids(sem_ids: List[str], lex_ids: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for cid in sem_ids + lex_ids:
        if cid and cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


# -------------------------
# Public API
# -------------------------
def hybrid_retrieval(query: str, top_k: int = 5, language: Optional[str] = None) -> List[Dict]:
    """
    Hybrid retrieval entrypoint (sync).
    Steps:
      1. Semantic search via embeddings + Pinecone (if available) -> get many candidates
      2. Lexical search via Postgres (if available)
      3. Merge candidate chunk_ids, fetch chunk text from Postgres
      4. Rerank candidates (cross-encoder / TF-IDF / simple) and return top_k
    """
    if not query or not query.strip():
        return []

    # 0) compute query embedding (sync)
    emb = None
    if embed_texts:
        try:
            emb = embed_texts([query])[0]
        except Exception as e:
            logger.exception("Failed to embed query: %s", e)
            emb = None
    else:
        logger.debug("Embedding service not available; skipping semantic search.")

    sem_candidates = []
    if emb is not None and _pinecone_index is not None:
        try:
            semantic_top_k = max(50, top_k * 10)  # fetch a larger candidate pool for reranking
            sem_matches = _semantic_search_pinecone(emb, top_k=semantic_top_k)
            # collect chunk ids and initial scores
            sem_candidates = [{"chunk_id": m["chunk_id"], "score": m["score"], "source": "pinecone", "metadata": m.get("metadata", {})} for m in sem_matches]
        except Exception as e:
            logger.exception("Semantic retrieval failed: %s", e)
            sem_candidates = []

    # Lexical search:
    lex_candidates = []
    try:
        lex_results = _lexical_search_sync(query, limit=max(50, top_k * 10), language=language)
        lex_candidates = [{"chunk_id": r["chunk_id"], "score": r["score"], "source": "lexical"} for r in lex_results]
    except Exception as e:
        logger.exception("Lexical retrieval failed: %s", e)
        lex_candidates = []

    # Merge ids preserving semantic-first order
    sem_ids = [c["chunk_id"] for c in sem_candidates]
    lex_ids = [c["chunk_id"] for c in lex_candidates]
    merged_ids = _merge_candidate_ids(sem_ids, lex_ids)

    if not merged_ids:
        logger.info("No candidates found for query.")
        return []

    # Fetch chunk texts from Postgres
    fetched = _fetch_chunks_by_ids_sync(merged_ids)
    # Map chunk_id -> text and metadata
    chunk_map = {r["chunk_id"]: r for r in fetched}

    # Build candidate objects combining score and text
    candidates = []
    # Use scores from sem_candidates or lex_candidates preferring semantic score if available
    score_map = {c["chunk_id"]: c["score"] for c in sem_candidates}
    # add lexical scores if not present
    for c in lex_candidates:
        if c["chunk_id"] not in score_map:
            score_map[c["chunk_id"]] = c["score"]

    for cid in merged_ids:
        r = chunk_map.get(cid)
        if r is None:
            # missing from DB — skip
            continue
        candidate = {
            "chunk_id": cid,
            "doc_id": r.get("doc_id"),
            "chunk_index": int(r.get("chunk_index")) if r.get("chunk_index") is not None else None,
            "text": r.get("text_snippet") or r.get("text')", "") if isinstance(r, dict) else "",
            "score": float(score_map.get(cid, 0.0)),
            "source": "pinecone" if cid in sem_ids else "lexical"
        }
        candidates.append(candidate)

    if not candidates:
        logger.info("No valid chunk texts retrieved.")
        return []

    # Rerank candidates if reranker available
    try:
        if rerank_candidates:
            # rerank expects query and list of candidates with 'text' fields
            reranked = rerank_candidates(query, candidates, top_k=top_k, method="cross-encoder")
            return reranked
        else:
            # fallback: sort by existing score and return top_k
            sorted_candidates = sorted(candidates, key=lambda x: x.get("score", 0.0), reverse=True)
            return sorted_candidates[:top_k]
    except Exception as e:
        logger.exception("Reranking failed: %s", e)
        sorted_candidates = sorted(candidates, key=lambda x: x.get("score", 0.0), reverse=True)
        return sorted_candidates[:top_k]
