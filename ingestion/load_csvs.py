#!/usr/bin/env python3
"""
ingestion/load_csvs.py

Developer helper script to ingest CSV files into the RAG knowledge base.

Usage:
    # single file
    python ingestion/load_csvs.py --path /path/to/file.csv

    # directory (walks non-recursively)
    python ingestion/load_csvs.py --path ./data/csvs --recursive

    # options:
    --max-rows N       limit per CSV (useful for testing)
    --doc-prefix name  prefix for generated doc_id
    --batch-size N     embedding batch size (default 64)
    --dry-run          don't upsert to Pinecone/Postgres; save prepared chunks to tmp_ingest/
"""

import os
import sys
import argparse
import logging
import uuid
import json
from pathlib import Path
from typing import List, Dict

# ensure repo root is importable when running script from repo root
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

logger = logging.getLogger("load_csvs")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Import ingestion helpers from the backend package
try:
    from backend.app.ingestion.csv_loader import load_csv
    from backend.app.ingestion.chunker import chunk_text_simple
    from backend.app.services.embeddings import embed_texts
    from backend.app.ingestion.upsert import upsert_chunks
    from backend.app.utils.file_utils import safe_filename, ensure_dir, write_json, compute_sha1
except Exception as e:
    logger.exception("Failed to import backend modules: %s", e)
    # We still allow running in a limited dry-run mode where imports may be missing.
    load_csv = None
    chunk_text_simple = None
    embed_texts = None
    upsert_chunks = None
    safe_filename = lambda n: n
    ensure_dir = lambda p: Path(p)
    write_json = lambda p, o: None
    compute_sha1 = lambda p: str(uuid.uuid4())


TMP_OUT = Path("tmp_ingest")
ensure_dir(str(TMP_OUT))


def discover_csv_paths(path: Path, recursive: bool = False) -> List[Path]:
    if path.is_file():
        return [path]
    if not path.exists():
        raise FileNotFoundError(path)
    if recursive:
        return [p for p in path.rglob("*.csv") if p.is_file()]
    else:
        return [p for p in path.glob("*.csv") if p.is_file()]


def make_doc_id(prefix: str, path: Path) -> str:
    # deterministic-ish: prefix + sha1 of file + basename
    try:
        h = compute_sha1(str(path))
    except Exception:
        # fallback to uuid
        h = uuid.uuid4().hex[:8]
    base = safe_filename(path.stem)
    return f"{prefix or 'csv'}:{base}:{h[:10]}"


def prepare_chunks_for_rows(rows: List[Dict], max_chunk_tokens: int = 500) -> List[Dict]:
    """
    Given rows from load_csv (each {'row_index','text'}), produce chunk metas for all rows.
    Each returned item includes: chunk_index, text, row_index
    """
    all_chunks = []
    chunk_counter = 0
    for r in rows:
        row_text = r.get("text", "")
        if not row_text or not row_text.strip():
            continue
        # chunk each row text (some rows are short and will be a single chunk)
        if chunk_text_simple:
            chunks = chunk_text_simple(row_text)
        else:
            # fallback simple split
            chunks = [{"chunk_index": 0, "text": row_text, "char_start": 0, "char_end": len(row_text)}]
        for c in chunks:
            c_meta = {
                "chunk_index": chunk_counter,
                "text": c.get("text") if isinstance(c, dict) else str(c),
                "char_start": c.get("char_start"),
                "char_end": c.get("char_end"),
                "row_index": r.get("row_index")
            }
            all_chunks.append(c_meta)
            chunk_counter += 1
    return all_chunks


def batch_iterable(it, batch_size):
    batch = []
    for x in it:
        batch.append(x)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def ingest_csv_file(path: Path, args) -> Dict:
    logger.info("Ingesting CSV: %s", path)
    doc_prefix = args.doc_prefix or "csv"
    max_rows = args.max_rows
    batch_size = args.batch_size or 64
    dry_run = args.dry_run

    # 1) Load rows
    if not load_csv:
        raise RuntimeError("csv_loader not available in PYTHONPATH.")
    rows = load_csv(str(path), max_rows=max_rows)
    logger.info("Loaded %d rows from %s", len(rows), path.name)
    if not rows:
        return {"ok": False, "reason": "no rows"}

    # 2) Create doc_id and metadata
    doc_id = make_doc_id(doc_prefix, path)
    docs_meta = {"source_type": "csv", "path": str(path), "title": path.name}

    # 3) create chunks from rows
    chunks_meta = prepare_chunks_for_rows(rows)
    logger.info("Prepared %d chunks (approx) for %s", len(chunks_meta), path.name)

    # Save intermediate chunks to tmp for inspection
    out_folder = TMP_OUT / safe_filename(path.stem)
    ensure_dir(str(out_folder))
    write_json(str(out_folder / "chunks_meta.json"), chunks_meta)
    write_json(str(out_folder / "rows_meta.json"), rows)
    logger.info("Wrote intermediate chunk metadata to %s", out_folder)

    # 4) Compute embeddings in batches
    embeddings = []
    if embed_texts is None:
        logger.warning("Embedding service not available — skipping embeddings (dry-run style).")
    else:
        texts = [c["text"] for c in chunks_meta]
        logger.info("Computing embeddings for %d chunks (batch_size=%d)", len(texts), batch_size)
        for i, batch in enumerate(batch_iterable(texts, batch_size)):
            logger.info("Embedding batch %d: size=%d", i + 1, len(batch))
            try:
                vecs = embed_texts(batch, batch_size=batch_size)
                embeddings.extend(vecs)
            except Exception as e:
                logger.exception("Embedding batch failed: %s", e)
                # fill with zero vectors to preserve alignment
                embeddings.extend([[0.0]] * len(batch))

    # 5) Upsert (if not dry-run)
    upsert_result = None
    if dry_run:
        logger.info("Dry-run enabled: skipping upsert. Prepared %d chunks and %d embeddings.", len(chunks_meta), len(embeddings))
        upsert_result = {"dry_run": True, "prepared_chunks": len(chunks_meta), "prepared_embeddings": len(embeddings)}
    else:
        if upsert_chunks is None:
            logger.warning("Upsert helper not available; cannot push to DB/Pinecone.")
            upsert_result = {"ok": False, "reason": "upsert unavailable", "prepared_chunks": len(chunks_meta)}
        else:
            # Ensure lengths match; if embeddings missing fill placeholder vectors
            if embeddings and len(embeddings) != len(chunks_meta):
                logger.warning("Embeddings count (%d) does not match chunks (%d). Padding with zeros.", len(embeddings), len(chunks_meta))
            # pad embeddings if necessary
            if embeddings and len(embeddings) < len(chunks_meta):
                missing = len(chunks_meta) - len(embeddings)
                embeddings.extend([[0.0]] * missing)
            if not embeddings:
                # we must still upsert chunk metadata but Pinecone will be skipped if not configured inside upsert
                logger.info("No embeddings computed; will still upsert chunk metadata if DB configured.")
            try:
                upsert_result = upsert_chunks(doc_id=doc_id, chunks_meta=chunks_meta, embeddings=embeddings, docs_meta=docs_meta)
                logger.info("Upsert result: %s", upsert_result)
            except Exception as e:
                logger.exception("Upsert failed: %s", e)
                upsert_result = {"ok": False, "error": str(e)}

    return {
        "doc_id": doc_id,
        "path": str(path),
        "chunks": len(chunks_meta),
        "embeddings": len(embeddings),
        "upsert": upsert_result
    }


def main():
    parser = argparse.ArgumentParser(description="Ingest CSV files into RAG KB (dev helper).")
    parser.add_argument("--path", "-p", required=True, help="Path to CSV file or directory containing CSVs.")
    parser.add_argument("--recursive", action="store_true", help="If path is a directory, search recursively.")
    parser.add_argument("--max-rows", type=int, default=None, help="Limit rows per CSV (for testing).")
    parser.add_argument("--doc-prefix", type=str, default="csv", help="Prefix for generated doc_id.")
    parser.add_argument("--batch-size", type=int, default=64, help="Embedding batch size.")
    parser.add_argument("--dry-run", action="store_true", help="Do not upsert to DB/Pinecone; just prepare chunks.")
    args = parser.parse_args()

    p = Path(args.path)
    if not p.exists():
        logger.error("Path does not exist: %s", p)
        sys.exit(2)

    csv_paths = discover_csv_paths(p, recursive=args.recursive)
    if not csv_paths:
        logger.error("No CSV files found at: %s", p)
        sys.exit(1)

    summary = []
    for csvp in csv_paths:
        try:
            res = ingest_csv_file(csvp, args)
            summary.append(res)
        except Exception as e:
            logger.exception("Failed ingesting %s: %s", csvp, e)
            summary.append({"path": str(csvp), "ok": False, "error": str(e)})

    summary_path = TMP_OUT / f"ingest_summary_{uuid.uuid4().hex[:8]}.json"
    write_json(str(summary_path), summary)
    logger.info("Ingestion complete. Summary written to %s", summary_path)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
