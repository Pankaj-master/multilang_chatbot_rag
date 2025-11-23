# backend/app/services/reranker.py
"""
Reranker for retrieved candidates.

Provides:
 - rerank_candidates(query, candidates, top_k=10, method="cross-encoder")
 - async_rerank_candidates(...) async wrapper

Candidates: list of dicts, each dict must have at least:
    {
      "doc_id": "...",
      "chunk_index": int,
      "text": "...",
      "score": <optional original retrieval score>
    }

Returns:
 - list of candidates sorted by 'rerank_score' (descending), trimmed to top_k.
"""

import logging
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor
import asyncio

logger = logging.getLogger("rag_app.reranker")

# Try to import CrossEncoder from sentence-transformers (best)
_has_crossencoder = False
try:
    from sentence_transformers import CrossEncoder  # type: ignore
    _has_crossencoder = True
except Exception:
    _has_crossencoder = False
    logger.debug("sentence-transformers CrossEncoder not available; falling back to TF-IDF reranker.")

# TF-IDF fallback
_has_sklearn = False
try:
    from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore
    from sklearn.metrics.pairwise import linear_kernel  # type: ignore
    _has_sklearn = True
except Exception:
    _has_sklearn = False
    logger.debug("scikit-learn not available; TF-IDF reranker disabled.")


# Default cross-encoder model to use if available
CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Thread pool for running sync work in async contexts
_executor = ThreadPoolExecutor(max_workers=6)


def _cross_encoder_score(query: str, texts: List[str]) -> List[float]:
    """
    Score relevance of each text to the query using a CrossEncoder model.
    Returns list of float scores (higher = more relevant).
    """
    if not _has_crossencoder:
        raise RuntimeError("CrossEncoder not installed.")
    try:
        model = CrossEncoder(CROSS_ENCODER_MODEL)
        # prepare pairs: [(query, text_i), ...]
        pairs = [[query, t] for t in texts]
        scores = model.predict(pairs, show_progress_bar=False)  # numpy array or list
        return [float(s) for s in scores]
    except Exception as e:
        logger.exception("Cross-encoder scoring failed: %s", e)
        # On failure return zeros
        return [0.0] * len(texts)


def _tfidf_score(query: str, texts: List[str]) -> List[float]:
    """
    TF-IDF + cosine similarity fallback.
    Returns list of float similarities.
    """
    if not _has_sklearn:
        raise RuntimeError("scikit-learn not installed.")
    try:
        # Build vectorizer on the candidate texts plus the query (to ensure consistent vector space)
        corpus = texts + [query]
        vectorizer = TfidfVectorizer().fit(corpus)
        doc_vecs = vectorizer.transform(texts)               # shape (n_texts, n_features)
        query_vec = vectorizer.transform([query])            # shape (1, n_features)
        sims = linear_kernel(query_vec, doc_vecs).flatten()  # similarities
        return [float(s) for s in sims]
    except Exception as e:
        logger.exception("TF-IDF scoring failed: %s", e)
        return [0.0] * len(texts)


def rerank_candidates(
    query: str,
    candidates: List[Dict],
    top_k: int = 10,
    method: str = "cross-encoder",
    return_all: bool = False,
) -> List[Dict]:
    """
    Re-rank candidate snippets.

    Args:
      query: user query string
      candidates: list of dicts with at least 'text'
      top_k: how many top results to return
      method: "cross-encoder" or "tfidf" or "simple"
      return_all: if True, return all candidates sorted; otherwise return top_k

    Returns:
      list of candidates augmented with 'rerank_score' (descending)
    """
    if not candidates:
        return []

    texts = [c.get("text", "") for c in candidates]

    method_to_use = method.lower() if method else "cross-encoder"

    scores = None
    if method_to_use == "cross-encoder":
        if _has_crossencoder:
            try:
                scores = _cross_encoder_score(query, texts)
            except Exception:
                logger.exception("Cross-encoder failed, falling back to TF-IDF.")
                method_to_use = "tfidf"
        else:
            logger.debug("Cross-encoder not available; switching to TF-IDF.")
            method_to_use = "tfidf"

    if method_to_use == "tfidf":
        if _has_sklearn:
            try:
                scores = _tfidf_score(query, texts)
            except Exception:
                logger.exception("TF-IDF failed; falling back to simple lexical scoring.")
                method_to_use = "simple"
        else:
            logger.debug("scikit-learn not available for TF-IDF. Using simple lexical scoring.")
            method_to_use = "simple"

    if method_to_use == "simple":
        # Simple heuristic: overlap of query words with text, normalized by length
        q_tokens = set([t.lower() for t in query.split() if len(t) > 2])
        scores = []
        for t in texts:
            t_tokens = set([w.lower() for w in t.split() if len(w) > 2])
            if not t_tokens:
                scores.append(0.0)
                continue
            overlap = q_tokens.intersection(t_tokens)
            score = len(overlap) / max(1.0, len(t_tokens))
            scores.append(float(score))

    # Combine with original retrieval score (if present) - simple linear interpolation
    final = []
    for cand, score in zip(candidates, scores):
        orig = cand.get("score")
        if orig is None:
            combined = float(score)
        else:
            # weight: reranker 0.8, original 0.2
            try:
                combined = 0.8 * float(score) + 0.2 * float(orig)
            except Exception:
                combined = float(score)
        new = dict(cand)  # copy
        new["rerank_score"] = float(combined)
        final.append(new)

    # sort descending by rerank_score
    final_sorted = sorted(final, key=lambda x: x.get("rerank_score", 0.0), reverse=True)

    if return_all:
        return final_sorted
    return final_sorted[:top_k]


# Async wrapper
async def async_rerank_candidates(query: str, candidates: List[Dict], top_k: int = 10, method: str = "cross-encoder") -> List[Dict]:
    """
    Async wrapper that executes rerank_candidates in threadpool to avoid blocking.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, lambda: rerank_candidates(query, candidates, top_k=top_k, method=method))


# Quick self-test if run directly
if __name__ == "__main__":
    sample_cands = [
        {"doc_id": "doc1", "chunk_index": 1, "text": "Mung beans are high in protein and low in fat. Per 100g, protein is 24g.", "score": 0.75},
        {"doc_id": "doc2", "chunk_index": 2, "text": "Rice contains carbohydrates and calories: 130 kcal per 100g. Protein is 2.7g.", "score": 0.6},
        {"doc_id": "doc3", "chunk_index": 3, "text": "Sprouted mung beans are nutritious and contain vitamins.", "score": 0.5},
    ]
    q = "protein in mung beans per 100g"
    out = rerank_candidates(q, sample_cands, top_k=3, method="simple")
    print("Rerank (simple):")
    for o in out:
        print(o["doc_id"], o["chunk_index"], o["rerank_score"])
