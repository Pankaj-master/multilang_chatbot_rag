# backend/app/retriever_chroma.py
'''import os
from dotenv import load_dotenv
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

load_dotenv('../../.env' if os.path.exists('../../.env') else '.env')
CHROMA_DIR = os.getenv('CHROMA_DIR', os.path.join(os.path.dirname(__file__), '../../ingestion/chroma_db'))
EMBED_MODEL_NAME = os.getenv('EMBED_MODEL_NAME', 'paraphrase-multilingual-MiniLM-L12-v2')

client = chromadb.Client(Settings(chroma_db_impl="duckdb+parquet", persist_directory=CHROMA_DIR))
collection = client.get_collection("warp_ayurvedic")
model = SentenceTransformer(EMBED_MODEL_NAME)

def retrieve(query: str, top_k: int = 5):
    # embed query
    q_emb = model.encode([query], convert_to_numpy=True)[0].tolist()
    res = collection.query(queries=[q_emb], n_results=top_k, include=['metadatas','documents','ids'])
    out = []
    if res and res.get('ids'):
        items = res['ids'][0]
        docs = res['documents'][0]
        metas = res['metadatas'][0]
        for _id, doc, meta in zip(items, docs, metas):
            out.append({'id': _id, 'text': doc, 'metadata': meta})
    return out'''