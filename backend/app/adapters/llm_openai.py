# backend/app/adapters/llm_openai.py.
'''
import os
from dotenv import load_dotenv
import openai
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env'))

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', None)
OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')  # change as desired

if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY

def build_prompt(query: str, contexts: list, language: str | None = None, options: dict | None = None):
    """
    Build a short structured prompt that includes:
    - system instruction (be concise, cite sources)
    - top contexts (with source labels)
    - user query
    Returns a string prompt (or dict if using chat completions).
    """
    sys = "You are an Ayurvedic diet assistant. Answer concisely and cite any sources you used by source label (e.g. [C1])."
    if language:
        sys += f" Reply in {language}."

    # attach contexts with labels
    ctx_lines = []
    for i, c in enumerate(contexts, start=1):
        meta = c.get('metadata', {})
        label = meta.get('source_id') if meta.get('table') == 'sources' else f"C{i}"
        snippet = c.get('text', '')[:800].replace("\n", " ")
        ctx_lines.append(f"[{label}] {snippet}")

    ctx_text = "\n\n".join(ctx_lines)
    prompt = f"{sys}\n\nCONTEXTS:\n{ctx_text}\n\nUser question: {query}\n\nAnswer and include short citations like [C1], [C2]. Keep answer ≤ 250 words."
    return prompt

def call_openai_sync(prompt: str, max_tokens: int = 400):
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set")
    # Use chat completions if desired (example uses chat completion API)
    response = openai.ChatCompletion.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "You are an Ayurvedic diet assistant. Give evidence-cited answers."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=max_tokens,
        temperature=0.2,
    )
    # extract text
    text = response['choices'][0]['message']['content'].strip()
    return {"answer": text, "meta": {"usage": response.get('usage')}}
