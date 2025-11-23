# backend/app/routes/ingest.py
import os
import uuid
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi import Body
from pydantic import BaseModel

logger = logging.getLogger("rag_app.ingest_router")

router = APIRouter()

# Simple in-memory job registry (replace with Redis/DB in production)
_JOB_REGISTRY: Dict[str, Dict[str, Any]] = {}

# Try to import the master ingestion pipeline (if implemented)
_pipeline_available = False
_ingest_module = None
try:
    from ..ingestion import ingest as ingest_module  # type: ignore
    _ingest_module = ingest_module
    _pipeline_available = True
    logger.info("Ingestion pipeline module loaded.")
except Exception as e:
    logger.warning("Ingestion pipeline module not available: %s", e)
    _pipeline_available = False


# Directory to persist uploaded files before ingestion
TMP_INGEST_DIR = Path(os.getenv("TMP_INGEST_DIR", "tmp_ingest"))
TMP_INGEST_DIR.mkdir(parents=True, exist_ok=True)


# ---- Request models ----
class IngestURLRequest(BaseModel):
    url: str
    source_type: Optional[str] = None  # e.g., "web", "api"
    doc_prefix: Optional[str] = None
    dry_run: Optional[bool] = True
    max_pages: Optional[int] = None
    ocr: Optional[bool] = False


# ---- Job helpers ----
def _create_job_record(task_type: str, meta: Dict[str, Any]) -> str:
    job_id = uuid.uuid4().hex
    _JOB_REGISTRY[job_id] = {
        "id": job_id,
        "status": "queued",
        "type": task_type,
        "meta": meta,
        "result": None,
        "error": None,
        "created_at": None,
    }
    logger.info("Created job %s (type=%s)", job_id, task_type)
    return job_id


def _set_job_status(job_id: str, status: str, result: Optional[Any] = None, error: Optional[str] = None):
    rec = _JOB_REGISTRY.get(job_id)
    if not rec:
        return
    rec["status"] = status
    if result is not None:
        rec["result"] = result
    if error is not None:
        rec["error"] = error


# ---- Background task runners ----
def _bg_ingest_file(job_id: str, file_path: str, source_type: Optional[str], doc_prefix: Optional[str], dry_run: bool, extra_opts: Dict[str, Any]):
    """
    Background worker that calls the ingestion pipeline to process a file.
    """
    logger.info("BG ingest file job %s starting for %s", job_id, file_path)
    _set_job_status(job_id, "running")
    try:
        if _pipeline_available and hasattr(_ingest_module, "ingest_file"):
            # expected signature: ingest_file(path, source_type=None, doc_prefix=None, dry_run=True, **opts)
            res = _ingest_module.ingest_file(file_path, source_type=source_type, doc_prefix=doc_prefix, dry_run=dry_run, **(extra_opts or {}))
        elif _pipeline_available and hasattr(_ingest_module, "ingest"):
            # fallback generic ingest interface
            res = _ingest_module.ingest({"file_path": file_path, "source_type": source_type, "doc_prefix": doc_prefix, "dry_run": dry_run, **(extra_opts or {})})
        else:
            # pipeline missing — keep file and return a dry-run summary
            res = {
                "dry_run": True,
                "note": "Ingestion pipeline not implemented. File saved for manual processing.",
                "file_path": file_path
            }
        _set_job_status(job_id, "succeeded", result=res)
        logger.info("BG ingest file job %s succeeded", job_id)
    except Exception as e:
        logger.exception("BG ingest file job %s failed: %s", job_id, e)
        _set_job_status(job_id, "failed", error=str(e))


def _bg_ingest_url(job_id: str, url: str, source_type: Optional[str], doc_prefix: Optional[str], dry_run: bool, extra_opts: Dict[str, Any]):
    """
    Background worker to ingest content from URL or API.
    """
    logger.info("BG ingest URL job %s starting for %s", job_id, url)
    _set_job_status(job_id, "running")
    try:
        if _pipeline_available and hasattr(_ingest_module, "ingest_from_url"):
            res = _ingest_module.ingest_from_url(url, source_type=source_type, doc_prefix=doc_prefix, dry_run=dry_run, **(extra_opts or {}))
        elif _pipeline_available and hasattr(_ingest_module, "ingest"):
            res = _ingest_module.ingest({"url": url, "source_type": source_type, "doc_prefix": doc_prefix, "dry_run": dry_run, **(extra_opts or {})})
        else:
            res = {
                "dry_run": True,
                "note": "Ingestion pipeline not implemented. URL queued for manual processing.",
                "url": url
            }
        _set_job_status(job_id, "succeeded", result=res)
        logger.info("BG ingest URL job %s succeeded", job_id)
    except Exception as e:
        logger.exception("BG ingest URL job %s failed: %s", job_id, e)
        _set_job_status(job_id, "failed", error=str(e))


# ---- Endpoints ----
@router.post("/upload", summary="Upload a file for ingestion")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    source_type: Optional[str] = Form(None),
    doc_prefix: Optional[str] = Form(None),
    dry_run: Optional[bool] = Form(True),
    ocr: Optional[bool] = Form(False),
    max_pages: Optional[int] = Form(None),
):
    """
    Upload a file (pdf/csv/xlsx) and schedule ingestion in background.
    Returns a job_id which can be polled via /status/{job_id}.
    """
    # Save uploaded file to tmp directory
    filename = Path(file.filename).name
    safe_name = f"{uuid.uuid4().hex}_{filename}"
    dest = TMP_INGEST_DIR / safe_name
    try:
        with dest.open("wb") as f:
            contents = await file.read()
            f.write(contents)
    except Exception as e:
        logger.exception("Failed to save uploaded file: %s", e)
        raise HTTPException(status_code=500, detail="Failed to save uploaded file.")

    # create job
    job_meta = {"filename": filename, "saved_path": str(dest), "source_type": source_type}
    job_id = _create_job_record("file", job_meta)

    # schedule background task
    extra_opts = {"ocr": ocr, "max_pages": max_pages}
    background_tasks.add_task(_bg_ingest_file, job_id, str(dest), source_type, doc_prefix, bool(dry_run), extra_opts)
    return {"job_id": job_id, "status": "queued"}


@router.post("/ingest_url", summary="Ingest content from a URL (web page or API)")
async def ingest_url(req: IngestURLRequest, background_tasks: BackgroundTasks):
    """
    Submit a URL to be ingested (web page, sitemap, API endpoint).
    """
    if not req.url:
        raise HTTPException(status_code=400, detail="url is required")
    job_meta = {"url": req.url, "source_type": req.source_type}
    job_id = _create_job_record("url", job_meta)
    extra_opts = {"max_pages": req.max_pages, "ocr": req.ocr}
    background_tasks.add_task(_bg_ingest_url, job_id, req.url, req.source_type, req.doc_prefix, bool(req.dry_run), extra_opts)
    return {"job_id": job_id, "status": "queued"}


class IngestLocalRequest(BaseModel):
    path: str
    source_type: Optional[str] = None
    doc_prefix: Optional[str] = None
    dry_run: Optional[bool] = True
    ocr: Optional[bool] = False
    max_pages: Optional[int] = None


@router.post("/ingest_local", summary="Ingest a file already on the host (dev-only)")
async def ingest_local(req: IngestLocalRequest, background_tasks: BackgroundTasks):
    """
    For development: ingest a file path that already exists on the server.
    """
    p = Path(req.path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="file not found")
    job_meta = {"path": str(p), "source_type": req.source_type}
    job_id = _create_job_record("local_file", job_meta)
    extra_opts = {"ocr": req.ocr, "max_pages": req.max_pages}
    background_tasks.add_task(_bg_ingest_file, job_id, str(p), req.source_type, req.doc_prefix, bool(req.dry_run), extra_opts)
    return {"job_id": job_id, "status": "queued"}


@router.get("/status/{job_id}", summary="Check ingestion job status")
async def job_status(job_id: str):
    rec = _JOB_REGISTRY.get(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "id": rec["id"],
        "status": rec["status"],
        "type": rec["type"],
        "meta": rec["meta"],
        "result": rec["result"],
        "error": rec["error"],
    }


@router.get("/jobs", summary="List recent ingestion jobs")
async def list_jobs(limit: int = 50):
    # list recent jobs in insertion order (not persisted across restarts)
    items = list(_JOB_REGISTRY.values())[::-1][:limit]
    return {"count": len(items), "jobs": items}
