# ingestion/upsert_vectors_faiss.py
import os
import pickle
import numpy as np
import psycopg2
from psycopg2.extras import DictCursor
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from tqdm import tqdm
import faiss

load_dotenv('../../.env' if os.path.exists('../../.env') else '.env')
DATABASE_URL = os.getenv('DATABASE_URL') or 'postgresql://postgres:postgres@localhost:5432/ragdb'
EMBED_MODEL_NAME = os.getenv('EMBED_MODEL_NAME', 'paraphrase-multilingual-MiniLM-L12-v2')
FAISS_INDEX_PATH = os.path.join(os.path.dirname(__file__), 'faiss_index.bin')
META_PATH = os.path.join(os.path.dirname(__file__), 'faiss_meta.pkl')

def get_conn():
    return psycopg2.connect(DATABASE_URL)

def fetch_foods():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT id, name, category, nutrients, dosha_properties, notes, raw_row FROM food_items;")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows

def fetch_sources():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute("SELECT source_id, title, type, language, author, publisher, year, source_url, notes FROM sources;")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows

def doc_text_from_food(row):
    name = row['name']
    category = row.get('category') or ''
    dosha = row.get('dosha_properties') or {}
    nutrients = row.get('nutrients') or {}
    notes = row.get('notes') or ''
    parts = [f"Food: {name}", f"Category: {category}"]
    if nutrients:
        parts.append("Nutrients: " + ", ".join(f"{k}: {v}" for k,v in nutrients.items()))
    if dosha:
        parts.append("Ayurvedic properties: " + ", ".join(f"{k}: {v}" for k,v in dosha.items()))
    if notes:
        parts.append("Notes: " + notes)
    return "\n\n".join(parts)

def doc_text_from_source(row):
    title = row.get('title') or row.get('source_id')
    typ = row.get('type') or ''
    notes = row.get('notes') or ''
    url = row.get('source_url') or ''
    parts = [f"Title: {title}", f"Type: {typ}"]
    if notes:
        parts.append("Notes: " + notes)
    if url:
        parts.append("URL: " + url)
    return "\n\n".join(parts)

def build_corpus():
    foods = fetch_foods()
    sources = fetch_sources()
    ids = []
    texts = []
    metas = []
    for r in foods:
        docid = f"food_{r['id']}"
        ids.append(docid)
        texts.append(doc_text_from_food(r))
        metas.append({'table':'food_items','row_id':r['id'],'name':r['name'],'category':r.get('category')})
    for r in sources:
        docid = f"source_{r['source_id']}"
        ids.append(docid)
        texts.append(doc_text_from_source(r))
        metas.append({'table':'sources','source_id':r['source_id'],'title':r.get('title'),'type':r.get('type')})
    return ids, texts, metas

def embed_texts(model, texts, batch_size=64):
    vectors = []
    for i in tqdm(range(0, len(texts), batch_size), desc="Embedding batches"):
        batch = texts[i:i+batch_size]
        embs = model.encode(batch, show_progress_bar=False, convert_to_numpy=True)
        vectors.append(embs)
    if vectors:
        return np.vstack(vectors).astype('float32')
    return np.zeros((0, model.get_sentence_embedding_dimension()), dtype='float32')

def normalize_vectors(vectors):
    # normalize to unit length for cosine similarity with inner product
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms

def main():
    print("Loading model:", EMBED_MODEL_NAME)
    model = SentenceTransformer(EMBED_MODEL_NAME)
    ids, texts, metas = build_corpus()
    if not texts:
        print("No documents found in DB.")
        return
    print(f"Docs to embed: {len(texts)}")
    vecs = embed_texts(model, texts)
    vecs = normalize_vectors(vecs)

    dim = vecs.shape[1]
    print("Vector dimension:", dim)

    # create FAISS index (IndexFlatIP over normalized vectors => cosine)
    index = faiss.IndexFlatIP(dim)
    index = faiss.IndexIDMap(index)  # allow custom integer ids
    # map string ids -> integer ids; keep a metadata dict for reverse lookup
    int_ids = np.arange(len(ids)).astype('int64')
    index.add_with_ids(vecs, int_ids)

    # persist index and metadata
    faiss.write_index(index, FAISS_INDEX_PATH)
    meta = {'ids': ids, 'texts': texts, 'metas': metas}
    with open(META_PATH, 'wb') as f:
        pickle.dump(meta, f)

    print("FAISS index saved to:", FAISS_INDEX_PATH)
    print("Metadata saved to:", META_PATH)
    print("Items upserted:", len(ids))

if __name__ == "__main__":
    main()
