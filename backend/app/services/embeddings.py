# backend/app/services/embeddings.py
"""
Embeddings service.

Provides:
  - embed_texts(texts: List[str]) -> List[List[float]]  (synchronous)
  - async_embed_texts(texts: List[str]) -> List[List[float]]  (async wrapper)

Supports providers:
  - "openai" (requires OPENAI_API_KEY env)
  - "local"  (sentence-transformers)
  - "gemini" / "perplexity" are placeholders (implement provider client calls)

Batching, retries, and optional caching are supported.

Environment variables:
  - EMBEDDING_PROVIDER  (openai | local | gemini | perplexity)
  - OPENAI_API_KEY
  - OPENAI_EMBEDDING_MODEL  (optional)
  - LOCAL_EMBEDDING_MODEL   (optional)
  - EMBEDDING_CACHE_TTL    (seconds, optional)
"""

import os
import time
import logging
from typing import List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor
import math

logger = logging.getLogger("rag_app.embeddings")

EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "gemini").lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "models/text-embedding-004")
LOCAL_EMBEDDING_MODEL = os.getenv("LOCAL_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "64"))
RETRY_COUNT = int(os.getenv("EMBEDDING_RETRY", "2"))
EMBEDDING_CACHE_TTL = int(os.getenv("EMBEDDING_CACHE_TTL", "86400"))  # 1 day default

# Optional caching (Redis) - import if available
_cache_available = False
try:
    from .cache import cache_get, cache_set, async_cache_get, async_cache_set  # type: ignore
    _cache_available = True
except Exception:
    _cache_available = False
    logger.debug("cache service not available for embeddings (optional).")

# Provider clients (optional)
_try_openai = False
try:
    import openai  # type: ignore
    _try_openai = True
except Exception:
    _try_openai = False

_try_sentence = False
_local_model = None
try:
    from sentence_transformers import SentenceTransformer  # type: ignore
    _try_sentence = True
except Exception:
    _try_sentence = False

_try_gemini = False
try:
    import google.generativeai as genai  # type: ignore
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
    _try_gemini = True
except Exception:
    _try_gemini = False


# ---------- Helper utilities ----------

def _compute_text_hash(s: str) -> str:
    # Simple stable hash for caching keys
    try:
        import hashlib
        h = hashlib.sha1(s.encode("utf-8")).hexdigest()
        return h
    except Exception:
        return str(abs(hash(s)))[:16]


def _batchify(items: List[str], batch_size: int):
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]


# ---------- Provider implementations ----------

def _openai_embed_batch(texts: List[str], model: Optional[str] = None) -> List[List[float]]:
    if not _try_openai:
        raise RuntimeError("openai package not installed or not available.")
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set in environment.")
    openai.api_key = OPENAI_API_KEY
    model_to_use = model or OPENAI_EMBEDDING_MODEL
    # OpenAI supports batching in a single call
    resp = openai.Embedding.create(model=model_to_use, input=texts)
    vectors = [d["embedding"] for d in resp["data"]]
    return vectors


def _local_embed_batch(texts: List[str], model_name: Optional[str] = None) -> List[List[float]]:
    global _local_model
    if not _try_sentence:
        raise RuntimeError("sentence-transformers not installed for local embeddings.")
    if _local_model is None:
        _local_model = SentenceTransformer(model_name or LOCAL_EMBEDDING_MODEL)
    vecs = _local_model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
    # convert numpy arrays to Python lists
    return [v.tolist() for v in vecs]


def _gemini_embed_batch(texts: List[str], model: Optional[str] = None) -> List[List[float]]:
    """
    Embed texts using Google Gemini API.
    """
    if not _try_gemini:
        raise RuntimeError("google-generativeai package not installed. Install with: pip install google-generativeai")
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set in environment.")
    
    model_to_use = model or GEMINI_EMBEDDING_MODEL
    
    # Gemini embedding API
    vectors = []
    for text in texts:
        result = genai.embed_content(
            model=model_to_use,
            content=text,
            task_type="retrieval_document"
        )
        vectors.append(result['embedding'])
    
    return vectors


def _perplexity_embed_batch_placeholder(texts: List[str]) -> List[List[float]]:
    raise NotImplementedError(
        "Perplexity embeddings are not implemented in this helper. "
        "Add provider-specific code for Perplexity embeddings."
    )


# ---------- Main sync API ----------

def _embed_batch_dispatcher(texts: List[str], provider: Optional[str] = None) -> List[List[float]]:
    prov = (provider or EMBEDDING_PROVIDER or "openai").lower()
    if prov == "openai":
        return _openai_embed_batch(texts)
    if prov == "local":
        return _local_embed_batch(texts)
    if prov == "gemini":
        return _gemini_embed_batch(texts)
    if prov == "perplexity":
        return _perplexity_embed_batch_placeholder(texts)
    raise RuntimeError(f"Unsupported embedding provider: {prov}")


def embed_texts(texts: List[str], provider: Optional[str] = None, batch_size: Optional[int] = None) -> List[List[float]]:
    """
    Synchronous embedding for a list of texts. Batches provider calls for efficiency.
    Uses caching when available.

    Args:
      texts: list of input strings
      provider: optional override of provider
      batch_size: optional override of batch size

    Returns:
      list of vectors (one per text)
    """
    if not texts:
        return []

    batch_size = int(batch_size or BATCH_SIZE)
    vectors: List[List[float]] = []
    to_process_indices = []
    cached_vectors = {}

    # 1) check cache (if available)
    if _cache_available:
        for idx, t in enumerate(texts):
            key = f"embed:{_compute_text_hash(t)}"
            try:
                cached = cache_get(key)
                if cached:
                    cached_vectors[idx] = cached
                else:
                    to_process_indices.append(idx)
            except Exception:
                # on cache error, skip caching
                to_process_indices.append(idx)
    else:
        to_process_indices = list(range(len(texts)))

    # 2) prepare result list with None placeholders
    vectors = [None] * len(texts)  # type: ignore

    # fill cached ones
    for idx, vec in cached_vectors.items():
        vectors[idx] = vec

    # 3) batch and compute embeddings for remaining
    if to_process_indices:
        # group texts into batches preserving order
        proc_texts = [texts[i] for i in to_process_indices]
        batches = list(_batchify(proc_texts, batch_size))
        base_idx = 0
        for batch in batches:
            success = False
            last_exc = None
            for attempt in range(RETRY_COUNT + 1):
                try:
                    emb_batch = _embed_batch_dispatcher(batch, provider=provider)
                    success = True
                    break
                except Exception as e:
                    last_exc = e
                    logger.warning("Embedding batch failed (attempt %d/%d): %s", attempt + 1, RETRY_COUNT + 1, e)
                    time.sleep(0.5 * (attempt + 1))
            if not success:
                logger.exception("Failed to embed batch after retries: %s", last_exc)
                # fill with empty vectors to keep alignment (may be undesirable)
                emb_batch = [[0.0]] * len(batch)

            # assign vectors back to the global result
            for i, emb in enumerate(emb_batch):
                idx_in_texts = to_process_indices[base_idx + i]
                vectors[idx_in_texts] = emb
                # cache if available
                if _cache_available:
                    try:
                        key = f"embed:{_compute_text_hash(texts[idx_in_texts])}"
                        cache_set(key, emb, ttl=EMBEDDING_CACHE_TTL)
                    except Exception:
                        pass
            base_idx += len(batch)

    # final sanity check
    for i, v in enumerate(vectors):
        if v is None:
            vectors[i] = [0.0]  # fallback vector
    return vectors


# ---------- Async API (wrapper) ----------

_executor = ThreadPoolExecutor(max_workers=8)


async def async_embed_texts(texts: List[str], provider: Optional[str] = None, batch_size: Optional[int] = None) -> List[List[float]]:
    """
    Async wrapper around embed_texts using ThreadPoolExecutor.
    Intended for use from async FastAPI endpoints.
    """
    loop = None
    try:
        import asyncio
        loop = asyncio.get_running_loop()
    except Exception:
        loop = None

    if not texts:
        return []

    # run in threadpool to avoid blocking event loop
    return await (loop.run_in_executor(_executor, lambda: embed_texts(texts, provider=provider, batch_size=batch_size)))


# ---------- Simple test harness ----------

if __name__ == "__main__":
    sample = ["hello world", "mung beans nutrition per 100g", "चावल के पोषक तत्व"]
    print("Embedding provider:", EMBEDDING_PROVIDER)
    try:
        vecs = embed_texts(sample)
        print("Got embeddings:", [len(v) for v in vecs])
    except Exception as e:
        print("Embedding failed:", e)
