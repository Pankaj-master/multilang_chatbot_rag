# backend/app/utils/text_cleaner.py
"""
Text cleaning and language-detection utilities used across the RAG pipeline.

Provides:
- detect_language(text) -> ISO language code (e.g., "en", "hi")
- clean_text(text, max_len=None) -> sanitized text (trimmed, normalized whitespace)
- extract_numbers(text) -> list of numeric strings/values found in text
- text_preview(text, chars=200) -> short snippet for logs/UIs

Language detection strategy:
1) Try `langdetect` (small, good)
2) If not available, try `fasttext` language-id (if installed and model provided)
3) Fallback to simple heuristic based on common script detection (Devanagari -> "hi", Latin -> "en", etc.)
"""

from typing import Optional, List
import logging
import re

logger = logging.getLogger("rag_app.text_cleaner")

# Try langdetect first
_try_langdetect = False
try:
    from langdetect import detect  # type: ignore
    _try_langdetect = True
except Exception:
    _try_langdetect = False
    logger.debug("langdetect not installed; falling back to other detectors.")

# Optional fastText (requires pretrained model to be set up)
_try_fasttext = False
_fasttext_model = None
try:
    import fasttext  # type: ignore
    _try_fasttext = True
    # Not loading a model here; user can call init_fasttext_model to provide a model path.
except Exception:
    _try_fasttext = False
    logger.debug("fasttext not available.")


# ------------------------------------------------------------
# fasttext helper (optional)
# ------------------------------------------------------------
def init_fasttext_model(model_path: str):
    """
    Load a fastText language identification model from `model_path`.
    Example model: lid.176.ftz (from fastText)
    """
    global _fasttext_model
    if not _try_fasttext:
        raise RuntimeError("fasttext library not installed.")
    try:
        _fasttext_model = fasttext.load_model(model_path)
        logger.info("Loaded fasttext model from %s", model_path)
    except Exception as e:
        logger.exception("Failed to load fasttext model: %s", e)
        _fasttext_model = None


# ------------------------------------------------------------
# Language detection
# ------------------------------------------------------------
def detect_language(text: str, default: str = "en") -> str:
    """
    Detect the language of `text`.
    Returns an ISO 639-1 code like 'en', 'hi', 'es' etc.
    Falls back to `default` if detection fails.
    """
    if not text or not text.strip():
        return default

    s = text.strip()
    # 1) try langdetect
    if _try_langdetect:
        try:
            code = detect(s)
            if code:
                return code
        except Exception:
            logger.debug("langdetect failed, trying fallback.")

    # 2) try fasttext if model loaded
    if _try_fasttext and _fasttext_model is not None:
        try:
            preds = _fasttext_model.predict(s.replace("\n", " "), k=1)  # returns (labels, probs)
            label = preds[0][0]  # e.g., "__label__en"
            if isinstance(label, str) and label.startswith("__label__"):
                return label.replace("__label__", "")
        except Exception:
            logger.debug("fasttext predict failed, trying script heuristic.")

    # 3) heuristic: check scripts / common words
    # Devanagari -> likely Hindi
    if re.search(r"[\u0900-\u097F]", s):
        return "hi"
    # Arabic script -> ar
    if re.search(r"[\u0600-\u06FF]", s):
        return "ar"
    # Cyrillic -> ru
    if re.search(r"[\u0400-\u04FF]", s):
        return "ru"
    # Simple English check via common words
    en_tokens = re.findall(r"\b(the|and|is|are|in|on|for|with)\b", s.lower())
    if len(en_tokens) >= 1:
        return "en"
    # Spanish common words
    es_tokens = re.findall(r"\b(el|la|y|es|en|para|con)\b", s.lower())
    if len(es_tokens) >= 1:
        return "es"
    # fallback default
    return default


# ------------------------------------------------------------
# Text cleaning helpers
# ------------------------------------------------------------
_re_control = re.compile(r"[\x00-\x1f\x7f-\x9f]")

def clean_text(text: Optional[str], max_len: Optional[int] = None, normalize_spaces: bool = True) -> str:
    """
    Clean input text:
    - Convert None -> ""
    - Remove control characters
    - Normalize whitespace
    - Trim to max_len (if provided) preserving words
    """
    if not text:
        return ""
    s = str(text)
    # remove control characters
    s = _re_control.sub(" ", s)
    # normalize unicode spaces and line breaks to single spaces
    if normalize_spaces:
        s = re.sub(r"\s+", " ", s)
    s = s.strip()
    if max_len and len(s) > max_len:
        # trim to last whitespace before max_len to avoid cutting words
        cut = s[: max_len].rfind(" ")
        if cut <= 0:
            s = s[:max_len]
        else:
            s = s[:cut]
    return s


# ------------------------------------------------------------
# Numeric extraction
# ------------------------------------------------------------
_number_re = re.compile(r"[-+]?\d{1,3}(?:[,\d]{0,}\d)?(?:\.\d+)?")  # matches numbers with optional commas/decimals

def extract_numbers(text: str) -> List[str]:
    """
    Extract numeric tokens from text (strings). Useful to find calories/protein values etc.
    Returns list of matched numeric strings.
    """
    if not text:
        return []
    matches = _number_re.findall(text)
    # normalize commas (e.g., "1,234" -> "1234")
    norm = [m.replace(",", "") for m in matches]
    return norm


# ------------------------------------------------------------
# Small helpers
# ------------------------------------------------------------
def text_preview(text: str, chars: int = 200) -> str:
    """
    Short preview suitable for logs: cleaned and truncated.
    """
    s = clean_text(text, max_len=chars)
    if len(s) >= chars:
        return s[: max(0, chars - 3)] + "..."
    return s


# ------------------------------------------------------------
# If run directly, quick self-test
# ------------------------------------------------------------
if __name__ == "__main__":
    samples = [
        "This is an English sentence. It mentions protein and calories.",
        "यह एक हिंदी वाक्य है जिसमें प्रोटीन और कैलोरीज़ का उल्लेख है।",
        "Proteínas por 100g: 24g, Calorías: 350 kcal",
        ""
    ]
    for t in samples:
        print("TEXT:", text_preview(t, chars=80))
        print("CLEAN:", clean_text(t, max_len=120))
        print("LANG:", detect_language(t))
        print("NUMS:", extract_numbers(t))
        print("---")
