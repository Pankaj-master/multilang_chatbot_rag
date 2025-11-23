#!/usr/bin/env python3
"""
test_conn.py

Run quick connectivity and dependency checks for the RAG app.

Checks:
 - Postgres (PG_DSN / DATABASE_URL)
 - Pinecone (PINECONE_API_KEY / PINECONE_ENV / PINECONE_INDEX)
 - Redis (REDIS_URL)
 - OpenAI (OPENAI_API_KEY) - basic Embedding API call if openai installed
 - Local sentence-transformers model availability
 - PyMuPDF (fitz) availability
 - Tesseract (pytesseract) availability (only checks import)
 - Requests availability

Usage:
    python test_conn.py
"""

import os
import sys
import json
import logging
import time

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("test_conn")

def test_postgres():
    dsn = os.getenv("PG_DSN") or os.getenv("DATABASE_URL")
    if not dsn:
        logger.warning("Postgres DSN not set (PG_DSN or DATABASE_URL). Skipping Postgres test.")
        return {"ok": False, "note": "PG_DSN not set"}
    try:
        import psycopg2
        conn = psycopg2.connect(dsn, connect_timeout=5)
        cur = conn.cursor()
        cur.execute("SELECT version();")
        v = cur.fetchone()
        conn.close()
        logger.info("Postgres connected: %s", v[0])
        return {"ok": True, "version": v[0]}
    except Exception as e:
        logger.exception("Postgres connection failed: %s", e)
        return {"ok": False, "error": str(e)}

def test_pinecone():
    api_key = os.getenv("PINECONE_API_KEY")
    env = os.getenv("PINECONE_ENV")
    index = os.getenv("PINECONE_INDEX", "kb-index")
    if not (api_key and env):
        logger.warning("Pinecone API key or env not set. Skipping Pinecone test.")
        return {"ok": False, "note": "Pinecone not configured"}
    try:
        import pinecone
        pinecone.init(api_key=api_key, environment=env)
        idxs = pinecone.list_indexes()
        logger.info("Pinecone init OK. Available indexes: %s", idxs)
        has_index = index in idxs
        return {"ok": True, "indexes": idxs, "has_index": has_index}
    except Exception as e:
        logger.exception("Pinecone test failed: %s", e)
        return {"ok": False, "error": str(e)}

def test_redis():
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        import redis
        client = redis.Redis.from_url(url, socket_connect_timeout=5)
        client.ping()
        logger.info("Redis ping OK (%s)", url)
        return {"ok": True, "url": url}
    except Exception as e:
        logger.exception("Redis test failed: %s", e)
        return {"ok": False, "error": str(e)}

def test_openai_embedding():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        logger.warning("OPENAI_API_KEY not set. Skipping OpenAI embedding test.")
        return {"ok": False, "note": "OPENAI_API_KEY not set"}
    try:
        import openai
        openai.api_key = key
        model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        # small trial call - wrap in try except to avoid raising
        try:
            resp = openai.Embedding.create(model=model, input=["test"])
            size = len(resp["data"][0]["embedding"])
            logger.info("OpenAI embedding OK (model=%s, dim=%d)", model, size)
            return {"ok": True, "model": model, "dim": size}
        except Exception as e:
            logger.exception("OpenAI API call failed: %s", e)
            return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.exception("openai package not installed or failed: %s", e)
        return {"ok": False, "error": str(e)}

def test_sentence_transformer():
    try:
        from sentence_transformers import SentenceTransformer
        model_name = os.getenv("LOCAL_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        logger.info("Loading sentence-transformers model '%s' (may take time)...", model_name)
        start = time.time()
        m = SentenceTransformer(model_name)
        vec = m.encode(["test"], show_progress_bar=False, convert_to_numpy=True)
        dt = time.time() - start
        logger.info("SentenceTransformer OK (model=%s) encode time %.2fs, dim=%d", model_name, dt, len(vec[0]))
        return {"ok": True, "model": model_name, "dim": len(vec[0]), "load_time_s": dt}
    except Exception as e:
        logger.exception("SentenceTransformer test failed: %s", e)
        return {"ok": False, "error": str(e)}

def test_modules():
    results = {}
    # requests
    try:
        import requests
        results["requests"] = {"ok": True}
    except Exception as e:
        results["requests"] = {"ok": False, "error": str(e)}
    # fitz / pymupdf
    try:
        import fitz
        results["pymupdf"] = {"ok": True}
    except Exception as e:
        results["pymupdf"] = {"ok": False, "error": str(e)}
    # pytesseract
    try:
        import pytesseract
        results["pytesseract"] = {"ok": True}
    except Exception as e:
        results["pytesseract"] = {"ok": False, "error": str(e)}
    # playwright (optional)
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
        results["playwright"] = {"ok": True}
    except Exception as e:
        results["playwright"] = {"ok": False, "error": str(e)}
    return results

def run_all():
    logger.info("Starting connectivity tests...")
    out = {}
    out["postgres"] = test_postgres()
    out["pinecone"] = test_pinecone()
    out["redis"] = test_redis()
    out["openai_embedding"] = test_openai_embedding()
    out["sentence_transformer"] = test_sentence_transformer()
    out["modules"] = test_modules()

    print("\n=== Summary ===")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    # Provide non-zero exit code if any critical service failed (Postgres is critical)
    critical_fail = not out["postgres"].get("ok", False)
    if critical_fail:
        logger.error("One or more critical services failed (Postgres). See summary above.")
        sys.exit(2)
    logger.info("Connectivity checks completed.")
    return out

if __name__ == "__main__":
    run_all()
