# backend/app/services/llm.py
"""
LLM wrapper for generation (Gemini / Perplexity / OpenAI fallback).

Provides:
  - async generate_answer(user_message, context, system_prompt, language, history)
    -> returns (answer_text, cards_list, buttons_list)

Design:
  - Build strict KB-only prompt that instructs model to ONLY use provided context snippets.
  - Request output in JSON: {"answer": "...", "cards": [...], "buttons": [...]}
  - Use temperature=0 (deterministic)
  - Attempt JSON parse; fallback to raw text if parse fails

Provider support:
  - OPENAI (openai package) is used as a convenient fallback for development.
  - GEMINI and PERPLEXITY placeholders are provided: implement provider-specific client calls where marked.
"""

import os
import json
import logging
import asyncio
from typing import Tuple, List, Optional, Dict, Any

logger = logging.getLogger("rag_app.llm")

# Provider selection via env
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()  # "openai" | "gemini" | "perplexity"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", None)
OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")  # fallback model
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", None)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

# Optional caching hooks
_try_cache = False
try:
    from .cache import async_cache_get, async_cache_set  # type: ignore
    _try_cache = True
except Exception:
    _try_cache = False

# Optional OpenAI import
_try_openai = False
try:
    import openai  # type: ignore
    _try_openai = True
except Exception:
    _try_openai = False
    logger.debug("openai package not installed; OpenAI fallback disabled.")

# Optional Google Generative AI import
_try_gemini = False
try:
    import google.generativeai as genai  # type: ignore
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
    _try_gemini = True
except Exception:
    _try_gemini = False
    logger.debug("google-generativeai package not installed; Gemini disabled.")


# -------------------------
# Prompt composition helper
# -------------------------
def _compose_system_and_user(system_prompt: str, context: str, user_message: str, language: str) -> List[Dict[str, str]]:
    """
    Return messages (list of {"role","content"}) for chat-style APIs.
    We instruct the model to output JSON with exact schema.
    """

    localized_fallbacks = {
        "en": "That's a great question — I couldn't find that information in the company's documentation.",
        "hi": "यह एक अच्छा प्रश्न है — मुझे कंपनी के दस्तावेज़ों में वह जानकारी नहीं मिली।",
    }
    fallback_sentence = localized_fallbacks.get(language.split("-")[0], localized_fallbacks["en"])

    instruction_block = (
        "INSTRUCTIONS:\n"
        "1) Answer using ONLY the information present in the CONTEXT SNIPPETS below. Do NOT hallucinate.\n"
        "2) For every factual claim include an inline citation pointing to the snippet source in parentheses, e.g. (Source: doc_id, chunk:3).\n"
        "3) If the answer cannot be found in the provided snippets, reply exactly with the fallback sentence:\n"
        f"   \"{fallback_sentence}\"\n"
        "4) Return output as JSON only (no extra prose) with the exact schema:\n"
        "{\n"
        '  "answer": "<string>",\n'
        '  "cards": [{"title":"...", "description":"...", "image_url":"...", "source_id":"..."}],\n'
        '  "buttons": [{"label":"...", "value":"..."}]\n'
        "}\n"
        "5) Answer in the user's language. If snippets were in a different language, you may use their translated text, but always include the source citation with the original doc_id.\n"
        "6) Use short, clear, helpful answers suitable for a health/nutrition website.\n"
        "7) Use temperature 0 for deterministic output.\n"
    )

    # Build messages: system prompt + user content that includes context
    system_msg = {"role": "system", "content": system_prompt}
    user_content = (
        f"User question (language={language}):\n{user_message}\n\n"
        "CONTEXT SNIPPETS:\n"
        f"{context}\n\n"
        f"{instruction_block}"
    )
    user_msg = {"role": "user", "content": user_content}
    return [system_msg, user_msg]


# -------------------------
# Provider-specific callers
# -------------------------

def _call_openai_chat_sync(messages: List[Dict[str, str]], model: Optional[str] = None, max_tokens: int = 800, temperature: float = 0.0) -> str:
    """
    Synchronous OpenAI ChatCompletion call (used from async wrapper via threadpool).
    """
    if not _try_openai:
        raise RuntimeError("openai package not installed.")
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set.")

    openai.api_key = OPENAI_API_KEY
    model_to_use = model or OPENAI_CHAT_MODEL

    resp = openai.ChatCompletion.create(
        model=model_to_use,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        n=1,
    )
    content = resp["choices"][0]["message"]["content"]
    return content


async def _call_openai_chat(messages: List[Dict[str, str]], model: Optional[str] = None, max_tokens: int = 800, temperature: float = 0.0) -> str:
    """
    Async wrapper around the synchronous openai call; runs in threadpool to avoid blocking.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _call_openai_chat_sync(messages, model=model, max_tokens=max_tokens, temperature=temperature))


def _call_gemini_sync(messages: List[Dict[str, str]], model: Optional[str] = None, max_tokens: int = 800, temperature: float = 0.0) -> str:
    """
    Synchronous Google Gemini API call.
    """
    if not _try_gemini:
        raise RuntimeError("google-generativeai package not installed. Install with: pip install google-generativeai")
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set.")
    
    model_to_use = model or GEMINI_MODEL
    gemini_model = genai.GenerativeModel(model_to_use)
    
    # Convert chat messages to Gemini format
    # Gemini expects alternating user/model messages or a single prompt
    # We'll combine system + user messages into a single prompt
    prompt_parts = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        if role == "system":
            prompt_parts.append(f"System Instructions: {content}")
        elif role == "user":
            prompt_parts.append(f"User: {content}")
        elif role == "assistant":
            prompt_parts.append(f"Assistant: {content}")
    
    full_prompt = "\n\n".join(prompt_parts)
    
    # Generate response
    response = gemini_model.generate_content(
        full_prompt,
        generation_config=genai.types.GenerationConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
        )
    )
    
    return response.text


async def _call_gemini(messages: List[Dict[str, str]], model: Optional[str] = None, max_tokens: int = 800, temperature: float = 0.0) -> str:
    """
    Async wrapper for Gemini API call.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: _call_gemini_sync(messages, model=model, max_tokens=max_tokens, temperature=temperature))


async def _call_perplexity_placeholder(messages: List[Dict[str, str]], **kwargs) -> str:
    """
    Placeholder for Perplexity API call.
    Implement provider-specific client here and return textual answer.
    """
    raise NotImplementedError("Perplexity call not implemented. Add provider-specific client code here.")


# -------------------------
# Main generation entrypoint
# -------------------------
async def generate_answer(
    user_message: str,
    context: str,
    system_prompt: str,
    language: str = "en",
    history: Optional[List[Dict[str, str]]] = None,
    max_tokens: int = 800,
    temperature: float = 0.0,
    model: Optional[str] = None,
    use_cache: bool = True,
) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Generate an answer using configured LLM provider.

    Returns:
      (answer_text, cards_list, buttons_list)

    cards_list: list of {"title","description","image_url","source_id"}
    buttons_list: list of {"label","value"}
    """
    # Try cache key
    cache_key = None
    if use_cache and _try_cache:
        try:
            key_input = f"{language}|{user_message}|{hash(context)}"
            cache_key = f"llm_resp:{abs(hash(key_input))}"
            cached = await async_cache_get(cache_key)
            if cached:
                logger.debug("LLM cache hit for key=%s", cache_key)
                return cached["answer"], cached.get("cards", []), cached.get("buttons", [])
        except Exception:
            # caching should not fail the flow
            logger.exception("LLM cache lookup failed (continuing): %s", cache_key)

    # Compose messages
    messages = _compose_system_and_user(system_prompt, context, user_message, language)
    # Optionally append history (as assistant/user messages) - we keep them as user messages below for transparency
    if history:
        for h in history:
            role = h.get("role", "user")
            content = h.get("content", "")
            if role and content:
                # append as user or assistant message to give context
                messages.append({"role": role, "content": content})

    # Select provider and call
    provider = LLM_PROVIDER
    raw_text = None
    last_exc = None
    for attempt in range(2):
        try:
            if provider == "openai":
                raw_text = await _call_openai_chat(messages, model=model, max_tokens=max_tokens, temperature=temperature)
            elif provider == "gemini":
                raw_text = await _call_gemini(messages, model=model, max_tokens=max_tokens, temperature=temperature)
            elif provider == "perplexity":
                raw_text = await _call_perplexity_placeholder(messages, model=model, max_tokens=max_tokens, temperature=temperature)
            else:
                raise RuntimeError(f"Unsupported LLM_PROVIDER={provider}")
            break
        except Exception as e:
            last_exc = e
            logger.warning("LLM provider call failed on attempt %d: %s", attempt + 1, e)
            await asyncio.sleep(0.5 * (attempt + 1))

    if raw_text is None:
        logger.exception("LLM generation failed: %s", last_exc)
        raise RuntimeError("LLM generation failed. See logs for details.")

    # The model is instructed to return JSON only. Attempt to parse.
    answer_text = ""
    cards: List[Dict[str, Any]] = []
    buttons: List[Dict[str, Any]] = []

    # Try robust JSON extraction: model might include markdown or backticks
    def _extract_json_from_text(s: str) -> Optional[str]:
        s = s.strip()
        # try direct parse
        try:
            json.loads(s)
            return s
        except Exception:
            pass
        # try to find first "{" and last "}" substring
        first = s.find("{")
        last = s.rfind("}")
        if first != -1 and last != -1 and last > first:
            candidate = s[first : last + 1]
            try:
                json.loads(candidate)
                return candidate
            except Exception:
                pass
        return None

    json_payload = _extract_json_from_text(raw_text)
    if json_payload:
        try:
            parsed = json.loads(json_payload)
            answer_text = parsed.get("answer", "") or ""
            cards = parsed.get("cards", []) or []
            buttons = parsed.get("buttons", []) or []
        except Exception as e:
            logger.exception("Failed to parse JSON from LLM output: %s", e)
            answer_text = raw_text.strip()
            cards = []
            buttons = []
    else:
        # Not valid JSON — fallback to plain text answer
        logger.warning("LLM did not return JSON. Returning raw text as answer.")
        answer_text = raw_text.strip()
        cards = []
        buttons = []

    # Cache result if available
    if use_cache and _try_cache and cache_key:
        try:
            await async_cache_set(cache_key, {"answer": answer_text, "cards": cards, "buttons": buttons}, ttl=3600)
        except Exception:
            logger.exception("LLM cache set failed for key=%s", cache_key)

    return answer_text, cards, buttons