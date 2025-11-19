# ingestion/upsert_vectors_chroma.py
'''import os, time
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import DictCursor
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from tqdm import tqdm
import json

load_dotenv('../../.env' if os.path.exists('../../.env') else '.env')
DATABASE_URL = os.getenv('DATABASE_URL') or 'postgresql://postgres:postgres@localhost:5432/ragdb'
CHROMA_DIR = os.getenv('CHROMA_DIR', os.path.join(os.path.dirname(__file__), 'chroma_db'))
EMBED_MODEL_NAME = os.getenv('EMBED_MODEL_NAME', 'paraphrase-multilingual-MiniLM-L12-v2')  # multilingual

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

def main():
    print("Loading embedding model:", EMBED_MODEL_NAME)
    model = SentenceTransformer(EMBED_MODEL_NAME)

    print("Initializing Chroma (local) at", CHROMA_DIR)
    client = chromadb.Client(Settings(chroma_db_impl="duckdb+parquet", persist_directory=CHROMA_DIR))
    # create or get collection
    collection_name = "warp_ayurvedic"
    try:
        collection = client.get_collection(collection_name)
    except Exception:
        collection = client.create_collection(collection_name, embedding_function=None)

    # Fetch DB rows
    foods = fetch_foods()
    sources = fetch_sources()
    print(f"Foods: {len(foods)}, Sources: {len(sources)}")

    docs = []
    metadatas = []
    ids = []
    texts = []

    for r in foods:
        docid = f"food_{r['id']}"
        text = doc_text_from_food(r)
        meta = {
            "table": "food_items",
            "row_id": r['id'],
            "name": r['name'],
            "category": r.get('category')
        }
        ids.append(docid)
        texts.append(text)
        metadatas.append(meta)

    for r in sources:
        docid = f"source_{r['source_id']}"
        text = doc_text_from_source(r)
        meta = {
            "table": "sources",
            "source_id": r['source_id'],
            "title": r.get('title'),
            "type": r.get('type'),
            "language": r.get('language')
        }
        ids.append(docid)
        texts.append(text)
        metadatas.append(meta)

    # embed in batches to avoid OOM
    batch_size = 64
    vectors = []
    print("Embedding", len(texts), "documents in batches of", batch_size)
    for i in tqdm(range(0, len(texts), batch_size)):
        batch = texts[i:i+batch_size]
        embs = model.encode(batch, show_progress_bar=False, convert_to_numpy=True)
        vectors.extend(embs.tolist())

    # upsert to chroma collection (replace existing with same ids)
    # if collection exists, delete same ids first to ensure update
    existing_ids = []
    try:
        existing = collection.get(ids=ids)
        existing_ids = [d['id'] for d in existing['ids']] if existing and existing.get('ids') else []
    except Exception:
        existing_ids = []

    if existing_ids:
        print("Deleting existing ids before upsert:", len(existing_ids))
        collection.delete(ids=existing_ids)

    print("Adding vectors to Chroma collection:", collection_name)
    collection.add(documents=texts, metadatas=metadatas, ids=ids, embeddings=vectors)
    client.persist()
    print("Upsert complete. Items upserted:", len(ids))

if __name__ == "__main__":
    main()
'''