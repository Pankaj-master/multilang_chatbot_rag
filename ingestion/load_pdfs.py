#!/usr/bin/env python3
"""
ingestion/load_pdfs.py

Developer helper script to ingest PDF files into the RAG knowledge base.

Usage:
    # single PDF
    python ingestion/load_pdfs.py --path /path/to/file.pdf

    # directory (walks non-recursively)
    python ingestion/load_pdfs.py --path ./data/pdfs --recursive

Options:
    --ocr                   run OCR on pages that yield no text (requires pdf2image + pytesseract)
    --dpi N                 DPI for pdf2image when OCRing (default 200)
    --max-pages N           limit pages per PDF (for testing)
    --doc-prefix name       prefix for generated doc_id
    --batch-size N          embedding batch size (default 64)
    --dry-run               prepare chunks but do not upsert to DB/Pinecone
    --recursive             look for PDFs recursively in directory
"""

import os
import sys
import argparse
import logging
import uuid
import json
from pathlib import Path
from typing import List, Dict

# make repo importable
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

logger = logging.getLogger("load_pdfs")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# backend imports (graceful fallback to limited dry-run)
try:
    from backend.app.ingestion.pdf_loader import load_pdf
    from backend.app.ingestion.chunker import chunk_text_simple
    from backend.app.services.embeddings import embed_texts
    from backend.app.ingestion.upsert import upsert_chunks
    from backend.app.utils.file_utils import safe_filename, ensure_dir, write_json, compute_sha1
except Exception as e:
    logger.exception("Failed to import backend modules: %s", e)
    load_pdf = None
    chunk_text_simple = None
    embed_texts = None
    upsert_chunks = None
    safe_filename = lambda n: n
    ensure_dir = lambda p: Path(p)
    write_json = lambda p, o: None
    compute_sha1 = lambda p: str(uuid.uuid4())

TMP_OUT = Path("tmp_ingest")
ensure_dir(str(TMP_OUT))


def discover_pdf_paths(path: Path, recursive: bool = False) -> List[Path]:
    if path.is_file():
        return [path]
    if not path.exists():
        raise FileNotFoundError(path)
    if recursive:
        return [p for p in path.rglob("*.pdf") if p.is_file()]
    else:
        return [p for p in path.glob("*.pdf") if p.is_file()]


def make_doc_id(prefix: str, path: Path) -> str:
    try:
        h = compute_sha1(str(path))
    except Exception:
        h = uuid.uuid4().hex[:8]
    base = safe_filename(path.stem)
    return f"{prefix or 'pdf'}:{base}:{h[:10]}"


def prepare_chunks_from_pages(pages: List[Dict], max_chunk_tokens: int = 500) -> List[Dict]:
    """
    pages: list of {"page": int, "text": "..."}
    returns list of chunk meta dicts:
      {"chunk_index": int, "text": "...", "page": page_num, "char_start":..., "char_end":...}
    """
    all_chunks = []
    chunk_counter = 0
    for p in pages:
        page_num = p.get("page")
        text = p.get("text", "") or ""
        if not text.strip():
            continue
        # chunk page text
        if chunk_text_simple:
            chunks = chunk_text_simple(text)
        else:
            # fallback: single chunk per page
            chunks = [{"chunk_index": 0, "text": text, "char_start": 0, "char_end": len(text)}]
        for c in chunks:
            c_meta = {
                "chunk_index": chunk_counter,
                "text": c.get("text") if isinstance(c, dict) else str(c),
                "char_start": c.get("char_start"),
                "char_end": c.get("char_end"),
                "page": page_num
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


def ingest_pdf_file(path: Path, args) -> Dict:
    logger.info("Ingesting PDF: %s", path)
    doc_prefix = args.doc_prefix or "pdf"
    dpi = args.dpi or 200
    ocr_when_empty = args.ocr
    max_pages = args.max_pages
    batch_size = args.batch_size or 64
    dry_run = args.dry_run

    if load_pdf is None:
        raise RuntimeError("pdf_loader not available in PYTHONPATH.")

    # 1) extract pages
    pages = load_pdf(str(path), ocr_when_empty=ocr_when_empty, dpi=dpi)
    logger.info("Extracted %d pages (raw) from %s", len(pages), path.name)

    if max_pages:
        pages = pages[:max_pages]
        logger.info("Truncated to max_pages=%d", max_pages)

    # 2) build doc metadata
    doc_id = make_doc_id(doc_prefix, path)
    docs_meta = {"source_type": "pdf", "path": str(path), "title": path.name}

    # 3) create chunks from pages
    chunks_meta = prepare_chunks_from_pages(pages)
    logger.info("Prepared %d chunks from %d pages (approx).", len(chunks_meta), len(pages))

    # Save intermediate metadata to tmp folder
    out_folder = TMP_OUT / safe_filename(path.stem)
    ensure_dir(str(out_folder))
    write_json(str(out_folder / "pages_meta.json"), pages)
    write_json(str(out_folder / "chunks_meta.json"), chunks_meta)
    logger.info("Wrote intermediate page/chunk metadata to %s", out_folder)

    # 4) Compute embeddings for chunk texts
    embeddings = []
    if embed_texts is None:
        logger.warning("Embedding service not available — skipping embeddings.")
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
                embeddings.extend([[0.0]] * len(batch))

    # 5) upsert or dry-run
    upsert_result = None
    if dry_run:
        logger.info("Dry-run enabled: skipping upsert. Prepared %d chunks and %d embeddings.", len(chunks_meta), len(embeddings))
        upsert_result = {"dry_run": True, "prepared_chunks": len(chunks_meta), "prepared_embeddings": len(embeddings)}
    else:
        if upsert_chunks is None:
            logger.warning("Upsert helper not available; cannot push to DB/Pinecone.")
            upsert_result = {"ok": False, "reason": "upsert unavailable", "prepared_chunks": len(chunks_meta)}
        else:
            if embeddings and len(embeddings) != len(chunks_meta):
                logger.warning("Embeddings count (%d) does not match chunks (%d). Padding with zeros.", len(embeddings), len(chunks_meta))
            if embeddings and len(embeddings) < len(chunks_meta):
                missing = len(chunks_meta) - len(embeddings)
                embeddings.extend([[0.0]] * missing)
            try:
                upsert_result = upsert_chunks(doc_id=doc_id, chunks_meta=chunks_meta, embeddings=embeddings, docs_meta=docs_meta)
                logger.info("Upsert result: %s", upsert_result)
            except Exception as e:
                logger.exception("Upsert failed: %s", e)
                upsert_result = {"ok": False, "error": str(e)}

    return {
        "doc_id": doc_id,
        "path": str(path),
        "pages": len(pages),
        "chunks": len(chunks_meta),
        "embeddings": len(embeddings),
        "upsert": upsert_result
    }


def main():
    parser = argparse.ArgumentParser(description="Ingest PDF files into RAG KB (dev helper).")
    parser.add_argument("--path", "-p", required=True, help="Path to PDF file or directory containing PDFs.")
    parser.add_argument("--recursive", action="store_true", help="If path is a directory, search recursively.")
    parser.add_argument("--ocr", action="store_true", help="Run OCR on empty pages (requires pdf2image and pytesseract).")
    parser.add_argument("--dpi", type=int, default=200, help="DPI for pdf2image when doing OCR.")
    parser.add_argument("--max-pages", type=int, default=None, help="Limit pages per PDF (for testing).")
    parser.add_argument("--doc-prefix", type=str, default="pdf", help="Prefix for generated doc_id.")
    parser.add_argument("--batch-size", type=int, default=64, help="Embedding batch size.")
    parser.add_argument("--dry-run", action="store_true", help="Do not upsert to DB/Pinecone; just prepare chunks.")
    args = parser.parse_args()

    p = Path(args.path)
    if not p.exists():
        logger.error("Path does not exist: %s", p)
        sys.exit(2)

    pdf_paths = discover_pdf_paths(p, recursive=args.recursive)
    if not pdf_paths:
        logger.error("No PDF files found at: %s", p)
        sys.exit(1)

    summary = []
    for pdfp in pdf_paths:
        try:
            res = ingest_pdf_file(pdfp, args)
            summary.append(res)
        except Exception as e:
            logger.exception("Failed ingesting %s: %s", pdfp, e)
            summary.append({"path": str(pdfp), "ok": False, "error": str(e)})

    summary_path = TMP_OUT / f"ingest_pdf_summary_{uuid.uuid4().hex[:8]}.json"
    write_json(str(summary_path), summary)
    logger.info("Ingestion complete. Summary written to %s", summary_path)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
