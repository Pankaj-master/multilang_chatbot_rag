# backend/app/routes/chat.py
import logging
from fastapi import APIRouter, HTTPException
from fastapi import Body
from pydantic import BaseModel
from typing import List, Optional

from ..services.retriever import hybrid_retrieval
from ..services.llm import generate_answer
from ..utils.text_cleaner import detect_language

router = APIRouter()
logger = logging.getLogger("rag_app.chat")


# ===== Request & Response Schemas =====

class ChatRequest(BaseModel):
    message: str
    history: Optional[List[dict]] = None  # [{"role": "user"/"assistant", "content": "..."}]
    language: Optional[str] = None        # user can force language
    top_k: int = 5                        # number of retrieved chunks


class ChatResponse(BaseModel):
    answer: str
    language: str
    sources: List[dict]     # [{"doc_id": "...", "chunk_index": 2, "score": 0.88}]
    cards: Optional[List[dict]] = None
    buttons: Optional[List[dict]] = None


# ===== Load system prompt =====

try:
    import os
    ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    prompt_path = os.path.join(ROOT, "prompts", "system_prompt.txt")

    with open(prompt_path, "r", encoding="utf-8") as f:
        SYSTEM_PROMPT = f.read().strip()

except Exception as e:
    logger.warning("system_prompt.txt not found. Using fallback minimal prompt.")
    SYSTEM_PROMPT = (
        "You are a RAG assistant. Answer ONLY using provided context. "
        "If the answer is not in the context, say: "
        "\"That's a great question — I couldn't find that information in the company's documentation.\""
    )


# ===== Chat Route =====

@router.post("/", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest = Body(...)):
    """
    Main RAG chatbot endpoint.
    Steps:
    1. Detect language (unless user provided it)
    2. Retrieve chunks (hybrid vector + keyword)
    3. Build LLM context
    4. Generate answer using Gemini/Perplexity
    5. Return structured response
    """

    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Empty message.")

    # -------- 1. Detect language --------
    user_lang = req.language or detect_language(req.message)
    logger.info(f"Detected language: {user_lang}")

    # -------- 2. Retrieve relevant chunks --------
    try:
        retrieved = hybrid_retrieval(req.message, top_k=req.top_k, language=user_lang)
    except Exception as e:
        logger.exception("Retrieval failed: %s", e)
        raise HTTPException(status_code=500, detail="Retrieval failed.")

    if len(retrieved) == 0:
        logger.info("No retrieved chunks. Returning fallback message.")
        fallback = "That's a great question — I couldn't find that information in the company's documentation."
        return ChatResponse(
            answer=fallback,
            language=user_lang,
            sources=[],
            cards=[],
            buttons=[]
        )

    # Build RAG context for the prompt
    context_blocks = []
    source_list = []

    for item in retrieved:
        ctx = f"[doc: {item['doc_id']} | chunk {item['chunk_index']}]\n{item['text']}"
        context_blocks.append(ctx)
        source_list.append({
            "doc_id": item["doc_id"],
            "chunk_index": item["chunk_index"],
            "score": item.get("score", None)
        })

    context_text = "\n\n---\n\n".join(context_blocks)

    # -------- 3. Call LLM (Gemini / Perplexity wrapper) --------
    try:
        answer, cards, buttons = await generate_answer(
            user_message=req.message,
            context=context_text,
            system_prompt=SYSTEM_PROMPT,
            language=user_lang,
            history=req.history or []
        )
    except Exception as e:
        logger.exception("LLM generation failed: %s", e)
        raise HTTPException(status_code=500, detail="LLM generation failed.")

    # -------- 4. Send response back --------
    return ChatResponse(
        answer=answer,
        language=user_lang,
        sources=source_list,
        cards=cards,
        buttons=buttons
    )
