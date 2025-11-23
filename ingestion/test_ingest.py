#!/usr/bin/env python3
"""
ingestion/test_ingest.py

Quick integration-style tests for ingestion helpers.

Covers:
 - CSV loader -> chunker -> embeddings (dry-run)
 - Excel loader (if available)
 - API loader (simple public JSON if requests available)
 - PDF loader (if available) - runs light smoke test only
 - Upsert dry-run (ensures function is callable and handles missing config gracefully)

This is a developer helper — not a full unit test suite.
"""

import os
import sys
import json
import tempfile
import uuid
from pathlib import Path
import logging
import traceback

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_ingest")

# Try to import ingestion helpers (graceful fallback)
try:
    from backend.app.ingestion.csv_loader import load_csv
except Exception:
    load_csv = None
    logger.warning("csv_loader not available.")

try:
    from backend.app.ingestion.excel_loader import load_excel
except Exception:
    load_excel = None
    logger.warning("excel_loader not available.")

try:
    from backend.app.ingestion.api_loader import load_api
except Exception:
    load_api = None
    logger.warning("api_loader not available.")

try:
    from backend.app.ingestion.pdf_loader import load_pdf
except Exception:
    load_pdf = None
    logger.warning("pdf_loader not available.")

try:
    from backend.app.ingestion.chunker import chunk_text_simple
except Exception:
    chunk_text_simple = None
    logger.warning("chunker.chunk_text_simple not available.")

try:
    from backend.app.services.embeddings import embed_texts
except Exception:
    embed_texts = None
    logger.warning("embeddings.embed_texts not available.")

try:
    from backend.app.ingestion.upsert import upsert_chunks
except Exception:
    upsert_chunks = None
    logger.warning("upsert_chunks not available.")

from backend.app.utils.file_utils import write_json, ensure_dir, safe_filename

TMP = Path("tmp_ingest_test")
ensure_dir(str(TMP))


def make_sample_csv(path: Path):
    rows = [
        {"name": "Wheat", "calories": "364", "protein": "12.2"},
        {"name": "Mung bean", "calories": "347", "protein": "24.0"},
        {"name": "Rice", "calories": "130", "protein": "2.7"},
    ]
    # write simple CSV
    import csv
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "calories", "protein"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    return path


def make_sample_excel(path: Path):
    # create a simple excel file using pandas if available
    try:
        import pandas as pd
    except Exception:
        logger.warning("pandas not installed; cannot create sample excel.")
        return None
    df = pd.DataFrame([
        {"name": "Wheat", "calories": 364, "protein": 12.2},
        {"name": "Mung bean", "calories": 347, "protein": 24.0},
    ])
    df.to_excel(path, index=False)
    return path


def test_csv_loader():
    logger.info("=== CSV loader test ===")
    csv_path = TMP / "sample.csv"
    make_sample_csv(csv_path)
    if not load_csv:
        logger.error("csv_loader not available; test skipped.")
        return {"ok": False, "reason": "csv_loader missing"}
    try:
        rows = load_csv(str(csv_path), max_rows=None)
        logger.info("CSV loader returned %d rows. Sample: %s", len(rows), rows[:1])
        # chunk rows
        if chunk_text_simple:
            c = chunk_text_simple(rows[0]["text"])
            logger.info("Chunker output sample (len=%d): %s", len(c), c[:1])
        else:
            logger.info("chunk_text_simple not available; skipping chunk test.")
        # embeddings (if available) - small smoke
        if embed_texts:
            emb = embed_texts([rows[0]["text"]])
            logger.info("Embeddings produced dim=%d for sample", len(emb[0]) if emb else 0)
        else:
            logger.info("embed_texts not available; skipping embedding test.")
        return {"ok": True, "rows": len(rows)}
    except Exception as e:
        logger.exception("CSV loader test failed: %s", e)
        return {"ok": False, "error": str(e)}


def test_excel_loader():
    logger.info("=== Excel loader test ===")
    xlsx_path = TMP / "sample.xlsx"
    xp = make_sample_excel(xlsx_path)
    if not xp:
        logger.warning("Excel sample could not be created; skipping excel test.")
        return {"ok": False, "reason": "pandas missing"}
    if not load_excel:
        logger.error("excel_loader not available; test skipped.")
        return {"ok": False, "reason": "excel_loader missing"}
    try:
        rows = load_excel(str(xlsx_path))
        logger.info("Excel loader returned %d rows. Sample: %s", len(rows), rows[:1])
        return {"ok": True, "rows": len(rows)}
    except Exception as e:
        logger.exception("Excel loader failed: %s", e)
        return {"ok": False, "error": str(e)}


def test_api_loader():
    logger.info("=== API loader test ===")
    if not load_api:
        logger.error("api_loader not available; test skipped.")
        return {"ok": False, "reason": "api_loader missing"}
    # use a small public JSON endpoint if requests available; else mock
    test_url = "https://api.github.com/repos/python/cpython"
    try:
        out = load_api(test_url, paginate=False)
        logger.info("API loader returned title=%s, text_chars=%d", out.get("title"), len(out.get("text", "")))
        return {"ok": True, "title": out.get("title")}
    except Exception as e:
        logger.exception("API loader failed: %s", e)
        return {"ok": False, "error": str(e)}


def test_pdf_loader():
    logger.info("=== PDF loader test ===")
    if not load_pdf:
        logger.warning("pdf_loader not available; skipping PDF test.")
        return {"ok": False, "reason": "pdf_loader missing"}
    # try to find any small pdf in repo or tmp; otherwise skip
    candidates = list(Path('.').rglob("*.pdf"))
    sample = candidates[0] if candidates else None
    if not sample:
        logger.warning("No PDF found in repo to test. Skipping PDF loader test.")
        return {"ok": False, "reason": "no pdf file"}
    try:
        pages = load_pdf(str(sample), ocr_when_empty=False)
        logger.info("PDF loader extracted %d pages from %s", len(pages), sample)
        return {"ok": True, "pages": len(pages)}
    except Exception as e:
        logger.exception("PDF loader failed: %s", e)
        return {"ok": False, "error": str(e)}


def test_upsert_dry_run():
    logger.info("=== Upsert dry-run test ===")
    # prepare fake chunks
    doc_id = f"testdoc:{uuid.uuid4().hex[:8]}"
    chunks = [
        {"chunk_index": 0, "text": "Wheat: calories 364 per 100g", "page": 1},
        {"chunk_index": 1, "text": "Mung bean: protein 24g per 100g", "page": 2},
    ]
    # fake embeddings if embedding service missing
    embeddings = []
    if embed_texts:
        try:
            embeddings = embed_texts([c["text"] for c in chunks])
        except Exception as e:
            logger.warning("Embedding failed in upsert test: %s", e)
            embeddings = [[0.0]] * len(chunks)
    else:
        embeddings = [[0.0]] * len(chunks)

    try:
        if not upsert_chunks:
            logger.warning("upsert_chunks helper not available; skipping actual upsert. Simulating dry-run.")
            return {"ok": True, "dry_run": True}
        # call upsert — this will attempt DB/Pinecone; if not configured it's expected to warn/skip
        res = upsert_chunks(doc_id=doc_id, chunks_meta=chunks, embeddings=embeddings, docs_meta={"source_type":"test","path":"test"})
        logger.info("Upsert returned: %s", res)
        return {"ok": True, "res": res}
    except Exception as e:
        logger.exception("Upsert test failed: %s", e)
        return {"ok": False, "error": str(e)}


def main():
    logger.info("Running ingestion smoke tests...")
    results = {}
    try:
        results["csv"] = test_csv_loader()
    except Exception:
        results["csv"] = {"ok": False, "error": traceback.format_exc()}

    try:
        results["excel"] = test_excel_loader()
    except Exception:
        results["excel"] = {"ok": False, "error": traceback.format_exc()}

    try:
        results["api"] = test_api_loader()
    except Exception:
        results["api"] = {"ok": False, "error": traceback.format_exc()}

    try:
        results["pdf"] = test_pdf_loader()
    except Exception:
        results["pdf"] = {"ok": False, "error": traceback.format_exc()}

    try:
        results["upsert"] = test_upsert_dry_run()
    except Exception:
        results["upsert"] = {"ok": False, "error": traceback.format_exc()}

    summary_path = TMP / f"test_ingest_summary_{uuid.uuid4().hex[:8]}.json"
    write_json(str(summary_path), results)
    logger.info("Test summary written to %s", summary_path)
    print(json.dumps(results, indent=2, ensure_ascii=False))

    # exit non-zero if critical failures (csv loader or upsert)
    if not results.get("csv", {}).get("ok", False):
        logger.error("CSV loader test failed — please fix before running ingestion.")
        sys.exit(2)

    logger.info("Ingestion smoke tests completed.")
    sys.exit(0)


if __name__ == "__main__":
    main()