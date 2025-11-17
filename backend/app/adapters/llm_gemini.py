# backend/app/adapters/llm_gemini.py
import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env'))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

def build_prompt(query: str, contexts: list, language: str | None = None):
    sys = "You are an Ayurvedic diet assistant. Use the retrieved evidence given below to answer concisely."
    sys += " Cite sources like [C1], [C2]."
    if language:
        sys += f" Reply in {language}."

    ctx_lines = []
    for i, c in enumerate(contexts, start=1):
        meta = c.get("metadata", {})
        if meta.get("table") == "sources":
            label = meta.get("source_id")
        else:
            label = f"C{i}"

        snippet = c["text"][:700].replace("\n", " ")
        ctx_lines.append(f"[{label}] {snippet}")

    ctx_text = "\n\n".join(ctx_lines)

    return f"""{sys}

CONTEXTS:
{ctx_text}

User Question: {query}

Answer clearly and cite the contexts using their labels like [C1], [C2].
Keep answer under 200 words.
"""

def call_gemini(prompt: str, max_output_tokens: int = 400):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set")

    model = genai.GenerativeModel(GEMINI_MODEL)
    response = model.generate_content(prompt, generation_config={"max_output_tokens": max_output_tokens})
    text = response.text.strip()
    return {
        "answer": text,
        "meta": {
            "model": GEMINI_MODEL
        }
    }
