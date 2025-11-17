# backend/app/api/chat_api.py
from fastapi import APIRouter
from pydantic import BaseModel
from app.retriever_faiss import retrieve
import textwrap
import os

# Try Gemini
GEMINI_AVAILABLE = False
try:
    from app.adapters.llm_gemini import build_prompt, call_gemini, GEMINI_API_KEY
    GEMINI_AVAILABLE = bool(GEMINI_API_KEY)
except:
    GEMINI_AVAILABLE = False

router = APIRouter()

class ChatReq(BaseModel):
    user_id: str | None = None
    message: str
    k: int | None = 5
    lang: str | None = None

def extract_key_sentences(text, max_sent=3):
    sents = [s.strip() for s in text.replace("\n"," ").split(".") if s.strip()]
    sents = sorted(sents, key=lambda x: -len(x))
    return sents[:max_sent]

def synthesize_answer_template(query, contexts):
    if not contexts:
        return "Sorry, I could not find relevant references."
    parts = []
    for c in contexts[:3]:
        s = extract_key_sentences(c["text"], 2)
        if s:
            parts.append(" / ".join(s))
    return textwrap.shorten(
        f"Based on the retrieved references: {' • '.join(parts)}",
        width=800
    )

@router.post("/chat")
async def chat(req: ChatReq):
    q = req.message
    k = req.k or 5
    contexts = retrieve(q, top_k=k)

    # Build citations
    citations = []
    for idx, c in enumerate(contexts, start=1):
        meta = c.get("metadata", {})
        if meta.get("table") == "sources":
            label = meta.get("source_id")
            citations.append({
                "label": label,
                "title": meta.get("title"),
                "type": meta.get("type")
            })
        else:
            label = f"C{idx}"
            citations.append({
                "label": label,
                "name": meta.get("name"),
                "table": meta.get("table")
            })

    # Use Gemini if API key exists
    if GEMINI_AVAILABLE:
        prompt = build_prompt(q, contexts, language=req.lang)
        try:
            llm = call_gemini(prompt)
            return {
                "answer": llm["answer"],
                "references": citations,
                "raw_contexts": contexts,
                "llm_meta": llm["meta"]
            }
        except Exception as e:
            # fallback
            fallback = synthesize_answer_template(q, contexts)
            return {
                "answer": fallback,
                "references": citations,
                "raw_contexts": contexts,
                "error": str(e)
            }

    # No Gemini key -> free template fallback
    answer = synthesize_answer_template(q, contexts)
    return {
        "answer": answer,
        "references": citations,
        "raw_contexts": contexts
    }

'''# backend/app/api/chat_api.py
from fastapi import APIRouter
from pydantic import BaseModel
from app.retriever_faiss import retrieve
import textwrap
import os

# try to import OpenAI adapter
OPENAI_AVAILABLE = False
try:
    from app.adapters.llm_openai import build_prompt, call_openai_sync, OPENAI_API_KEY
    OPENAI_AVAILABLE = bool(OPENAI_API_KEY)
except Exception:
    OPENAI_AVAILABLE = False

router = APIRouter()

class ChatReq(BaseModel):
    user_id: str | None = None
    message: str
    k: int | None = 5
    lang: str | None = None

def extract_key_sentences(text, max_sent=3):
    sents = [s.strip() for s in text.replace("\n", " ").split(".") if s.strip()]
    sents = sorted(sents, key=lambda x: -len(x))
    return sents[:max_sent]

def synthesize_answer_template(query, contexts):
    if not contexts:
        return "Sorry — I couldn't find specific references for that query."
    snippets = []
    for c in contexts[:3]:
        parts = extract_key_sentences(c['text'], max_sent=2)
        if parts:
            snippets.append(" / ".join(parts))
    answer = f"Based on {len(contexts)} retrieved references: " + " • ".join(snippets)
    return textwrap.shorten(answer, width=800, placeholder="...")

@router.post("/chat")
async def chat(req: ChatReq):
    q = req.message
    k = req.k or 5
    contexts = retrieve(q, top_k=k)

    # Build citations metadata for client
    citations = []
    for idx, c in enumerate(contexts, start=1):
        meta = c.get('metadata', {})
        if meta.get('table') == 'sources':
            label = meta.get('source_id')
            citations.append({"label": label, "title": meta.get('title'), "type": meta.get('type')})
        else:
            label = f"C{idx}"
            citations.append({"label": label, "name": meta.get('name'), "table": meta.get('table')})

    # If OpenAI key available, call LLM for final answer
    if OPENAI_AVAILABLE:
        prompt = build_prompt(q, contexts, language=req.lang)
        try:
            llm_resp = call_openai_sync(prompt)
            answer_text = llm_resp.get('answer') or llm_resp.get('text') or ""
            return {
                "answer": answer_text,
                "references": citations,
                "raw_contexts": contexts[:k],
                "llm_meta": llm_resp.get('meta', {})
            }
        except Exception as e:
            # fallback to template if LLM call fails
            fallback = synthesize_answer_template(q, contexts)
            return {"answer": fallback, "references": citations, "raw_contexts": contexts[:k], "llm_error": str(e)}

    # No OpenAI -> use free template synthesizer
    answer = synthesize_answer_template(q, contexts)
    return {"answer": answer, "references": citations, "raw_contexts": contexts[:k]} #for OPEN
'''