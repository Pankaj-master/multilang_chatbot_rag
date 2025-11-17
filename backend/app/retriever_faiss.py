# backend/app/retriever_faiss.py
import os, pickle
import numpy as np
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
import faiss

load_dotenv('../../.env' if os.path.exists('../../.env') else '.env')
EMBED_MODEL_NAME = os.getenv('EMBED_MODEL_NAME', 'paraphrase-multilingual-MiniLM-L12-v2')
FAISS_INDEX_PATH = os.path.join(os.path.dirname(__file__), '../../ingestion/faiss_index.bin')
META_PATH = os.path.join(os.path.dirname(__file__), '../../ingestion/faiss_meta.pkl')

# load model and index on import
_model = SentenceTransformer(EMBED_MODEL_NAME)

if not os.path.exists(FAISS_INDEX_PATH) or not os.path.exists(META_PATH):
    raise RuntimeError("FAISS index or metadata not found. Run ingestion/upsert_vectors_faiss.py first.")

_index = faiss.read_index(FAISS_INDEX_PATH)
with open(META_PATH, 'rb') as f:
    _meta = pickle.load(f)  # dict with keys 'ids','texts','metas'

def _normalize(v):
    v = v.astype('float32').reshape(1, -1)
    norm = np.linalg.norm(v, axis=1, keepdims=True)
    if norm[0,0] == 0:
        return v
    return v / norm

def retrieve(query: str, top_k: int = 5):
    q_emb = _model.encode([query], convert_to_numpy=True)[0].astype('float32')
    q_emb = _normalize(q_emb)
    D, I = _index.search(q_emb, top_k)
    results = []
    for score, idx in zip(D[0], I[0]):
        if idx == -1:
            continue
        meta = _meta['metas'][int(idx)]
        text = _meta['texts'][int(idx)]
        sid = _meta['ids'][int(idx)]
        results.append({'id': sid, 'score': float(score), 'text': text, 'metadata': meta})
    return results
