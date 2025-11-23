# backend/app/ingestion/chunker.py
import logging
from typing import List, Dict, Optional

logger = logging.getLogger("rag_app.chunker")

# Try to import tiktoken for accurate tokenization (used for OpenAI/GPT style models)
try:
    import tiktoken  # type: ignore
    _has_tiktoken = True
except Exception:
    _has_tiktoken = False
    logger.debug("tiktoken not installed; falling back to char-based token estimation.")


def _count_tokens_tiktoken(text: str, encoder_name: str = "gpt2") -> int:
    enc = tiktoken.get_encoding(encoder_name)
    return len(enc.encode(text))


def _estimate_tokens_by_chars(text: str) -> int:
    # Conservative estimate: 1 token ≈ 4 characters (English average).
    return max(1, len(text) // 4)


def _get_token_count(text: str, encoder_name: str = "gpt2") -> int:
    if _has_tiktoken:
        try:
            return _count_tokens_tiktoken(text, encoder_name=encoder_name)
        except Exception:
            logger.exception("tiktoken failed, falling back to char estimation")
            return _estimate_tokens_by_chars(text)
    else:
        return _estimate_tokens_by_chars(text)


def chunk_text(
    text: str,
    *,
    max_tokens: int = 500,
    overlap_tokens: int = 50,
    encoder_name: str = "gpt2",
) -> List[Dict]:
    """
    Split `text` into token-aware overlapping chunks.
    Returns list of dicts: {"chunk_index", "text", "char_start", "char_end"}.

    Parameters:
    - max_tokens: target maximum tokens per chunk (including overlap).
    - overlap_tokens: number of tokens to overlap between adjacent chunks.
    - encoder_name: tiktoken encoder name (if tiktoken available); defaults to 'gpt2'.

    Behavior:
    - If tiktoken is available, uses token-based sliding window.
    - Otherwise approximates tokens using characters and does character-based slicing.
    """
    if not text:
        return []

    # Fast path if using char-based approximation
    if not _has_tiktoken:
        # estimate chars per token
        chars_per_token = 4  # conservative
        max_chars = max(64, max_tokens * chars_per_token)
        overlap_chars = max(16, overlap_tokens * chars_per_token)
        chunks = []
        start = 0
        idx = 0
        n = len(text)
        while start < n:
            end = min(start + max_chars, n)
            # try to break at newline or space for clean boundaries
            if end < n:
                # find last newline or space before end within a window
                split_at = text.rfind("\n", start, end)
                if split_at == -1:
                    split_at = text.rfind(" ", start, end)
                if split_at != -1 and split_at > start + 20:
                    end = split_at
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append({"chunk_index": idx, "text": chunk_text, "char_start": start, "char_end": end})
                idx += 1
            start = end - overlap_chars
            if start <= 0:
                start = end
        return chunks

    # Token-aware sliding window using tiktoken
    enc = tiktoken.get_encoding(encoder_name)
    tokens = enc.encode(text)
    total_tokens = len(tokens)
    if total_tokens == 0:
        return []

    chunks = []
    start_token = 0
    idx = 0
    while start_token < total_tokens:
        end_token = min(start_token + max_tokens, total_tokens)
        chunk_tokens = tokens[start_token:end_token]
        try:
            chunk_text = enc.decode(chunk_tokens).strip()
        except Exception:
            # fallback: decode safely via bytes
            chunk_text = text  # less ideal, but prevents crash
        # Find char offsets for snippet
        # We'll approximate char_start by decoding tokens up to start_token
        try:
            prefix = enc.decode(tokens[:start_token])
            char_start = len(prefix)
            char_end = char_start + len(chunk_text)
        except Exception:
            # fallback: naive approximation based on characters per token
            chars_per_token = 4
            char_start = max(0, start_token * chars_per_token)
            char_end = min(len(text), end_token * chars_per_token)

        chunks.append({"chunk_index": idx, "text": chunk_text, "char_start": char_start, "char_end": char_end})
        idx += 1
        # advance window with overlap
        start_token = end_token - overlap_tokens
        if start_token <= 0:
            start_token = end_token

    return chunks


# Convenience wrapper for default behavior
def chunk_text_simple(text: str) -> List[Dict]:
    """
    Simple default chunking using recommended parameters.
    """
    return chunk_text(text, max_tokens=500, overlap_tokens=50, encoder_name="gpt2")


if __name__ == "__main__":
    # Quick self-test
    sample = "This is a test. " * 200
    ch = chunk_text(sample, max_tokens=60, overlap_tokens=10)
    print(f"Generated {len(ch)} chunks.")
    for c in ch[:3]:
        print(c["chunk_index"], c["char_start"], c["char_end"], c["text"][:50])
