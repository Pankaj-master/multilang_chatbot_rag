# backend/app/ingestion/ingest.py
import os
import uuid
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("rag_app.ingest")

# Helpers & modules (best-effort imports; fallbacks handled)
try:
    from ..ingestion.pdf_loader import load_pdf
except Exception:
    load_pdf = None
    logger.debug("pdf_loader not available.")

try:
    from ..ingestion.csv_loader import load_csv
except Exception:
    load_csv = None
    logger.debug("csv_loader not available.")

try:
    from ..ingestion.excel_loader import load_excel
except Exception:
    load_excel = None
    logger.debug("excel_loader not available.")

try:
    from ..ingestion.web_loader import load_web  # assumed function
except Exception:
    load_web = None
    logger.debug("web_loader not available.")

try:
    from ..ingestion.api_loader import load_api
except Exception:
    load_api = None
    logger.debug("api_loader not available.")

try:
    from ..ingestion.chunker import chunk_text_simple
except Exception:
    chunk_text_simple = None
    logger.debug("chunker not available; using naive chunker fallback.")

try:
    from ..ingestion.upsert import upsert_chunks
except Exception:
    upsert_chunks = None
    logger.debug("upsert helper not available; upsert will be skipped in dry-run style.")

# embeddings
try:
    from ..services.embeddings import embed_texts
except Exception:
    embed_texts = None
    logger.debug("embeddings service not available; embeddings will be skipped.")

# utils
try:
    from ..utils.file_utils import ensure_dir, safe_filename, write_json, compute_sha1
except Exception:
    # minimal fallbacks
    def ensure_dir(p): Path(p).mkdir(parents=True, exist_ok=True); return Path(p)
    def safe_filename(n): return n
    def write_json(p, o): pass
    def compute_sha1(x): return uuid.uuid4().hex[:8]

try:
    from ..utils.text_cleaner import detect_language
except Exception:
    def detect_language(s, default="en"): return default

TMP_INGEST = Path(os.getenv("TMP_INGEST_DIR", "tmp_ingest"))
TMP_INGEST.mkdir(parents=True, exist_ok=True)


# -------------------------
# Internal helpers
# -------------------------
def _make_doc_id(prefix: Optional[str], path_or_name: str) -> str:
    # deterministic-ish doc id
    try:
        h = compute_sha1(path_or_name)
    except Exception:
        h = uuid.uuid4().hex[:8]
    base = safe_filename(Path(path_or_name).stem if "." in path_or_name else str(path_or_name))
    return f"{prefix or 'doc'}:{base}:{h[:10]}"


def _chunk_text(text: str) -> List[Dict[str, Any]]:
    """
    Return list of chunk dict: {"chunk_index", "text", "char_start", "char_end"}
    """
    if not text:
        return []
    if chunk_text_simple:
        out = chunk_text_simple(text)
        # chunk_text_simple may return dicts or strings; normalize
        chunks = []
        for i, c in enumerate(out):
            if isinstance(c, dict):
                chunks.append({
                    "chunk_index": i,
                    "text": c.get("text") or c.get("content") or "",
                    "char_start": c.get("char_start"),
                    "char_end": c.get("char_end")
                })
            else:
                txt = str(c)
                chunks.append({"chunk_index": i, "text": txt, "char_start": None, "char_end": None})
        return chunks
    # fallback: naive split by paragraphs up to ~1000 chars
    pieces = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    idx = 0
    for p in pieces:
        if len(p) <= 1200:
            chunks.append({"chunk_index": idx, "text": p, "char_start": None, "char_end": None})
            idx += 1
        else:
            # split long paragraph into ~1000-char slices
            start = 0
            while start < len(p):
                seg = p[start:start + 1000]
                chunks.append({"chunk_index": idx, "text": seg, "char_start": start, "char_end": start + len(seg)})
                start += 1000
                idx += 1
    return chunks


def _prepare_chunks_from_pages(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Pages: list of {"page": int, "text": "..."}
    Returns chunks with page info.
    """
    all_chunks = []
    counter = 0
    for p in pages:
        page_num = p.get("page")
        text = p.get("text") or ""
        if not text.strip():
            continue
        chunks = _chunk_text(text)
        for c in chunks:
            c_meta = {
                "chunk_index": counter,
                "text": c.get("text"),
                "page": page_num,
                "char_start": c.get("char_start"),
                "char_end": c.get("char_end"),
            }
            all_chunks.append(c_meta)
            counter += 1
    return all_chunks


def _prepare_chunks_from_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Rows: list of {"row_index":int, "text": "...", ...}
    Returns chunk list with row_index
    """
    all_chunks = []
    counter = 0
    for r in rows:
        text = r.get("text") or ""
        if not text.strip():
            continue
        chunks = _chunk_text(text)
        for c in chunks:
            c_meta = {
                "chunk_index": counter,
                "text": c.get("text"),
                "row_index": r.get("row_index"),
                "char_start": c.get("char_start"),
                "char_end": c.get("char_end"),
            }
            all_chunks.append(c_meta)
            counter += 1
    return all_chunks


def _compute_embeddings_for_texts(texts: List[str], batch_size: int = 64) -> List[List[float]]:
    """
    Compute embeddings in batches. If embed_texts not available, returns empty list.
    """
    if not embed_texts:
        return []
    out_vectors = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        try:
            vecs = embed_texts(batch, batch_size=batch_size)
            out_vectors.extend(vecs)
        except Exception as e:
            logger.exception("Embedding batch failed: %s", e)
            out_vectors.extend([[0.0]] * len(batch))
    return out_vectors


# -------------------------
# Public API
# -------------------------
def ingest_file(
    file_path: str,
    source_type: Optional[str] = None,
    doc_prefix: Optional[str] = None,
    dry_run: bool = True,
    ocr: bool = False,
    max_pages: Optional[int] = None,
    batch_size: int = 64,
) -> Dict[str, Any]:
    """
    Ingest a local file (pdf/csv/xlsx). Returns ingestion summary.

    - file_path: local path to the file
    - source_type: optional override for source_type (e.g., "pdf","csv")
    - doc_prefix: prefix for generated doc_id
    - dry_run: if True, don't call upsert_chunks; write intermediate JSON to tmp_ingest
    - ocr: if True and loader supports it, run OCR
    - max_pages: for PDFs limit page count
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(file_path)

    ext = p.suffix.lower()
    inferred = source_type or (("pdf" if ext == ".pdf" else ("csv" if ext == ".csv" else ("excel" if ext in [".xls", ".xlsx"] else "file"))))

    logger.info("Starting ingest_file: %s (type=%s) dry_run=%s", file_path, inferred, dry_run)

    doc_id = _make_doc_id(doc_prefix, str(p))
    docs_meta = {"source_type": inferred, "path": str(p), "title": p.name}

    chunks_meta = []
    # 1) Load and chunk according to type
    if inferred == "pdf":
        if not load_pdf:
            raise RuntimeError("PDF loader not available.")
        pages = load_pdf(str(p), ocr_when_empty=ocr)
        if max_pages:
            pages = pages[:max_pages]
        chunks_meta = _prepare_chunks_from_pages(pages)
    elif inferred == "csv":
        if not load_csv:
            raise RuntimeError("CSV loader not available.")
        rows = load_csv(str(p))
        chunks_meta = _prepare_chunks_from_rows(rows)
    elif inferred == "excel":
        if not load_excel:
            raise RuntimeError("Excel loader not available.")
        rows = load_excel(str(p))
        chunks_meta = _prepare_chunks_from_rows(rows)
    else:
        # generic: read text file
        text = p.read_text(encoding="utf-8", errors="ignore")
        chunks = _chunk_text(text)
        chunks_meta = [{"chunk_index": i, "text": c.get("text"), "char_start": c.get("char_start"), "char_end": c.get("char_end")} for i, c in enumerate(chunks)]

    # Save intermediate metadata for inspection
    out_dir = TMP_INGEST / safe_filename(doc_id)
    ensure_dir(str(out_dir))
    write_json(str(out_dir / "docs_meta.json"), docs_meta)
    write_json(str(out_dir / "chunks_meta_preembed.json"), chunks_meta)

    # 2) Compute embeddings
    texts = [c["text"] for c in chunks_meta]
    embeddings = _compute_embeddings_for_texts(texts, batch_size=batch_size) if texts else []

    write_json(str(out_dir / "embeddings_meta.json"), {"count": len(embeddings)})

    # 3) Upsert or dry-run
    upsert_result = None
    if dry_run:
        upsert_result = {"dry_run": True, "prepared_chunks": len(chunks_meta), "prepared_embeddings": len(embeddings)}
        logger.info("Dry-run ingest complete for %s: chunks=%d embeddings=%d", file_path, len(chunks_meta), len(embeddings))
    else:
        if upsert_chunks is None:
            upsert_result = {"ok": False, "reason": "upsert_chunks not available"}
            logger.warning("upsert_chunks not available; skipping actual upsert.")
        else:
            try:
                upsert_result = upsert_chunks(doc_id=doc_id, chunks_meta=chunks_meta, embeddings=embeddings, docs_meta=docs_meta)
                logger.info("Upsert finished for %s -> %s", file_path, upsert_result)
            except Exception as e:
                logger.exception("Upsert failed: %s", e)
                upsert_result = {"ok": False, "error": str(e)}

    # 4) return summary
    summary = {
        "doc_id": doc_id,
        "path": str(p),
        "source_type": inferred,
        "chunks": len(chunks_meta),
        "embeddings": len(embeddings),
        "upsert": upsert_result,
        "tmp_dir": str(out_dir)
    }
    return summary


def ingest_from_url(
    url: str,
    source_type: Optional[str] = None,
    doc_prefix: Optional[str] = None,
    dry_run: bool = True,
    max_pages: Optional[int] = None,
    batch_size: int = 64,
) -> Dict[str, Any]:
    """
    Ingest content from a URL (web page or API).
    - load_web / load_api functions are tried depending on source_type or URL heuristics.
    """
    logger.info("Starting ingest_from_url: %s", url)
    # choose loader: api if contains api or returns json, else web
    loader = None
    inferred = source_type
    text_blocks = []
    title = None

    # If api loader present and source_type=='api' or url looks like api/json -> try it first
    if (source_type and source_type.lower() == "api") or (load_api and ("api" in url or url.endswith(".json"))):
        try:
            res = load_api(url, paginate=False)
            title = res.get("title") or url
            text_blocks = [{"page": 0, "text": res.get("text", "")}]
            inferred = "api"
            loader = "api"
        except Exception as e:
            logger.warning("API loader failed for %s: %s; falling back to web loader", url, e)

    if not text_blocks:
        if load_web:
            try:
                pages = load_web(url, max_pages=max_pages)
                # load_web assumed to return list of pages: {"page":i,"text":"...", "title": "..."}
                title = pages[0].get("title") if pages and pages[0].get("title") else url
                text_blocks = pages
                inferred = "web"
                loader = "web"
            except Exception as e:
                logger.exception("Web loader failed for %s: %s", url, e)
        else:
            raise RuntimeError("No web or api loader available to ingest URL.")

    # build doc_id and docs_meta
    doc_id = _make_doc_id(doc_prefix, url)
    docs_meta = {"source_type": inferred, "path": url, "title": title or url}

    # chunk pages
    chunks_meta = _prepare_chunks_from_pages(text_blocks)
    out_dir = TMP_INGEST / safe_filename(doc_id)
    ensure_dir(str(out_dir))
    write_json(str(out_dir / "docs_meta.json"), docs_meta)
    write_json(str(out_dir / "chunks_meta_preembed.json"), chunks_meta)

    # embeddings
    texts = [c["text"] for c in chunks_meta]
    embeddings = _compute_embeddings_for_texts(texts, batch_size=batch_size) if texts else []
    write_json(str(out_dir / "embeddings_meta.json"), {"count": len(embeddings)})

    # upsert
    upsert_result = None
    if dry_run:
        upsert_result = {"dry_run": True, "prepared_chunks": len(chunks_meta), "prepared_embeddings": len(embeddings)}
    else:
        if upsert_chunks is None:
            upsert_result = {"ok": False, "reason": "upsert_chunks not available"}
        else:
            try:
                upsert_result = upsert_chunks(doc_id=doc_id, chunks_meta=chunks_meta, embeddings=embeddings, docs_meta=docs_meta)
            except Exception as e:
                logger.exception("Upsert failed for URL ingest: %s", e)
                upsert_result = {"ok": False, "error": str(e)}

    return {
        "doc_id": doc_id,
        "url": url,
        "source_type": inferred,
        "chunks": len(chunks_meta),
        "embeddings": len(embeddings),
        "upsert": upsert_result,
        "tmp_dir": str(out_dir)
    }


def ingest(input_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generic ingest entrypoint. Accepts a dict with keys:
      - file_path OR url
      - source_type (optional)
      - doc_prefix (optional)
      - dry_run (bool)
      - ocr, max_pages, batch_size

    Returns the chosen ingest function's result.
    """
    if "file_path" in input_dict:
        return ingest_file(
            file_path=input_dict.get("file_path"),
            source_type=input_dict.get("source_type"),
            doc_prefix=input_dict.get("doc_prefix"),
            dry_run=bool(input_dict.get("dry_run", True)),
            ocr=bool(input_dict.get("ocr", False)),
            max_pages=input_dict.get("max_pages"),
            batch_size=int(input_dict.get("batch_size", 64)),
        )
    elif "url" in input_dict:
        return ingest_from_url(
            url=input_dict.get("url"),
            source_type=input_dict.get("source_type"),
            doc_prefix=input_dict.get("doc_prefix"),
            dry_run=bool(input_dict.get("dry_run", True)),
            max_pages=input_dict.get("max_pages"),
            batch_size=int(input_dict.get("batch_size", 64)),
        )
    else:
        raise ValueError("input must contain 'file_path' or 'url'")
