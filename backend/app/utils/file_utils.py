# backend/app/utils/file_utils.py
"""
File utilities for ingestion & storage.

Common helpers:
 - ensure_dir(path)
 - safe_filename(name)
 - save_bytes(path, bytes_data)
 - save_text(path, text)
 - read_text(path)
 - read_json(path)
 - write_json(path, obj)
 - download_to_file(url, dest_path, max_bytes=5_000_000, timeout=15)
 - compute_sha1(path_or_bytes)
 - list_files(directory, extensions=None)
"""

import os
import io
import json
import hashlib
import logging
from pathlib import Path
from typing import Optional, Any, List

logger = logging.getLogger("rag_app.file_utils")


def ensure_dir(path: str) -> Path:
    """
    Ensure a directory exists. Returns Path object.
    """
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_filename(name: str, max_length: int = 240) -> str:
    """
    Produce a filesystem-safe filename (keeps extension if present).
    Removes dangerous characters and truncates if needed.
    """
    if not name:
        return "unnamed"
    # normalize separators
    name = name.replace("\\", "_").replace("/", "_")
    # remove control chars
    name = "".join(ch for ch in name if 32 <= ord(ch) < 127)
    # collapse spaces
    name = "_".join(name.split())
    if len(name) > max_length:
        # try to keep extension
        parts = name.rsplit(".", 1)
        if len(parts) == 2:
            ext = "." + parts[1][:10]
            base = parts[0][: max_length - len(ext)]
            name = base + ext
        else:
            name = name[:max_length]
    return name


def save_bytes(path: str, bytes_data: bytes, overwrite: bool = True) -> str:
    """
    Save bytes to path. Returns absolute path string.
    """
    p = Path(path)
    ensure_dir(str(p.parent))
    if p.exists() and not overwrite:
        raise FileExistsError(f"File exists and overwrite=False: {p}")
    with p.open("wb") as f:
        f.write(bytes_data)
    return str(p.resolve())


def save_text(path: str, text: str, encoding: str = "utf-8", overwrite: bool = True) -> str:
    """
    Save UTF-8 text to file.
    """
    return save_bytes(path, text.encode(encoding), overwrite=overwrite)


def read_text(path: str, encoding: str = "utf-8") -> str:
    """
    Read text from file. Returns empty string if file not found.
    """
    p = Path(path)
    if not p.exists():
        logger.debug("read_text: file not found %s", path)
        return ""
    with p.open("r", encoding=encoding, errors="ignore") as f:
        return f.read()


def write_json(path: str, obj: Any, indent: int = 2, overwrite: bool = True) -> str:
    """
    Write JSON-serializable object to file.
    """
    txt = json.dumps(obj, ensure_ascii=False, indent=indent)
    return save_text(path, txt, overwrite=overwrite)


def read_json(path: str) -> Optional[Any]:
    """
    Read JSON file and return object, or None on failure.
    """
    p = Path(path)
    if not p.exists():
        logger.debug("read_json: file not found %s", path)
        return None
    try:
        with p.open("r", encoding="utf-8", errors="ignore") as f:
            return json.load(f)
    except Exception as e:
        logger.exception("read_json failed for %s: %s", path, e)
        return None


def compute_sha1(path_or_bytes: Any) -> str:
    """
    Compute SHA1 of a file path or bytes object.
    """
    h = hashlib.sha1()
    if isinstance(path_or_bytes, (bytes, bytearray)):
        h.update(path_or_bytes)
        return h.hexdigest()
    p = Path(path_or_bytes)
    if not p.exists():
        raise FileNotFoundError(path_or_bytes)
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def list_files(directory: str, extensions: Optional[List[str]] = None, recursive: bool = False) -> List[str]:
    """
    List files in a directory, optionally filtering by extensions (e.g. ['.pdf', '.csv']).
    Returns absolute paths as strings.
    """
    p = Path(directory)
    if not p.exists():
        return []
    exts = None
    if extensions:
        exts = set(e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensions)
    files = []
    if recursive:
        it = p.rglob("*")
    else:
        it = p.iterdir()
    for item in it:
        if not item.is_file():
            continue
        if exts:
            if item.suffix.lower() not in exts:
                continue
        files.append(str(item.resolve()))
    return files


def download_to_file(url: str, dest_path: str, max_bytes: int = 5_000_000, timeout: int = 15) -> Optional[str]:
    """
    Download a URL to a file with size limit. Returns path on success, None on failure.
    Uses requests (if available); otherwise raises RuntimeError.
    """
    try:
        import requests  # type: ignore
    except Exception:
        raise RuntimeError("requests required for download_to_file. Install with `pip install requests`.")

    try:
        resp = requests.get(url, stream=True, timeout=timeout)
        resp.raise_for_status()
        ensure_dir(str(Path(dest_path).parent))
        total = 0
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    logger.warning("download_to_file: exceeded max_bytes for %s", url)
                    return None
                f.write(chunk)
        return str(Path(dest_path).resolve())
    except Exception as e:
        logger.exception("download_to_file failed for %s: %s", url, e)
        return None
