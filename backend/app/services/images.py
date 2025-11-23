# backend/app/services/images.py
"""
Image utilities for the RAG pipeline:
 - download image safely (size limits)
 - generate thumbnail
 - optional CLIP/vision embeddings (placeholder for later)
 - optional S3 upload (prepared, not required)
 - base64 encoding for frontend delivery
"""

import io
import os
import logging
import base64
import requests
from PIL import Image
from typing import Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("rag_app.images")

MAX_DOWNLOAD_SIZE = int(os.getenv("IMAGE_MAX_DOWNLOAD_SIZE", 5_000_000))  # 5 MB
TIMEOUT = int(os.getenv("IMAGE_TIMEOUT", 10))  # seconds
THUMB_SIZE = int(os.getenv("IMAGE_THUMB_SIZE", 256))
ALLOWED_FORMATS = ("jpeg", "jpg", "png", "webp")

_executor = ThreadPoolExecutor(max_workers=8)


# ---------------------------------------------------------
# Download image (sync)
# ---------------------------------------------------------
def _download_image(url: str) -> Optional[bytes]:
    """
    Download image with size limit and timeout.
    Returns raw bytes or None.
    """
    try:
        with requests.get(url, stream=True, timeout=TIMEOUT) as r:
            r.raise_for_status()

            total = 0
            chunks = []
            for chunk in r.iter_content(1024 * 32):
                total += len(chunk)
                if total > MAX_DOWNLOAD_SIZE:
                    logger.warning("Image too large: %s (%d bytes)", url, total)
                    return None
                chunks.append(chunk)
            return b"".join(chunks)

    except Exception as e:
        logger.warning("Image download failed for %s: %s", url, e)
        return None


# ---------------------------------------------------------
# Image processing
# ---------------------------------------------------------
def _load_pil(img_bytes: bytes) -> Optional[Image.Image]:
    try:
        return Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception as e:
        logger.warning("Failed to open image with PIL: %s", e)
        return None


def generate_thumbnail(img: Image.Image, size: int = THUMB_SIZE) -> bytes:
    """
    Generate a square thumbnail in JPEG format, return raw bytes.
    """
    try:
        image = img.copy()
        image.thumbnail((size, size))

        out = io.BytesIO()
        image.save(out, format="JPEG", quality=85)
        return out.getvalue()
    except Exception as e:
        logger.warning("Thumbnail generation failed: %s", e)
        return b""


# ---------------------------------------------------------
# Public API
# ---------------------------------------------------------
def fetch_and_prepare_image(url: str) -> Optional[Dict[str, Any]]:
    """
    Download → load → generate thumbnail → base64 encode.
    Output:
      {
        "url": url,
        "original_b64": "...",
        "thumbnail_b64": "...",
        "width": int,
        "height": int
      }
    """
    raw = _download_image(url)
    if not raw:
        return None

    pil_img = _load_pil(raw)
    if pil_img is None:
        return None

    width, height = pil_img.size

    thumb = generate_thumbnail(pil_img)

    result = {
        "url": url,
        "original_b64": base64.b64encode(raw).decode("utf-8"),
        "thumbnail_b64": base64.b64encode(thumb).decode("utf-8") if thumb else None,
        "width": width,
        "height": height
    }

    return result


async def async_fetch_and_prepare_image(url: str) -> Optional[Dict[str, Any]]:
    """
    Async wrapper for fetch_and_prepare_image using thread pool.
    """
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, lambda: fetch_and_prepare_image(url))


# ---------------------------------------------------------
# CLIP Image Embeddings (Optional Placeholder)
# ---------------------------------------------------------
def compute_image_embedding_placeholder(img_bytes: bytes) -> Optional[list]:
    """
    Placeholder: integrate your CLIP or vision encoder here.
    For example:
      - OpenAI CLIP
      - local CLIP model (sentence-transformers)
      - Gemini / Perplexity vision encoder

    Return:
      list of floats
    """
    raise NotImplementedError(
        "Image embedding not implemented. Add CLIP/Gemini vision embedding here."
    )


# ---------------------------------------------------------
# Optional S3 uploader stub (for future website integration)
# ---------------------------------------------------------
def upload_to_s3_placeholder(file_bytes: bytes, key: str) -> str:
    """
    Stub: Upload to S3 or Cloudflare R2.
    Should return public URL.
    """
    raise NotImplementedError(
        "S3 upload not implemented. Add boto3 or Cloudflare R2 client here."
    )
