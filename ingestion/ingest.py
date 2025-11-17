# ingestion/ingest.py  (updated - sanitizes NaN and numpy types)
import os, json, pandas as pd
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import Json, DictCursor
import numpy as np

load_dotenv('../../.env' if os.path.exists('../../.env') else '.env')
DATABASE_URL = os.getenv('DATABASE_URL') or 'postgresql://postgres:postgres@localhost:5432/ragdb'

def get_conn():
    return psycopg2.connect(DATABASE_URL)

def _clean_value(v):
    # convert pandas/numpy NaN -> None, numpy types -> native python, keep dict/list cleaned
    if v is None:
        return None
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return None
    if isinstance(v, (np.floating, np.float32, np.float64)):
        return float(v)
    if isinstance(v, (np.integer, np.int32, np.int64)):
        return int(v)
    if isinstance(v, (np.bool_, )):
        return bool(v)
    if isinstance(v, (list, tuple)):
        return [_clean_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _clean_value(val) for k, val in v.items()}
    # pandas NaT / Timestamp handling
    try:
        import pandas as pd
        if isinstance(v, pd.Timestamp):
            return v.isoformat()
        if pd.isna(v):
            return None
    except Exception:
        pass
    # fallback: keep as-is (str, int, etc)
    return v

def _clean_row_dict(row_dict):
    return {k: _clean_value(v) for k, v in row_dict.items()}

def upsert_foods(csv_path):
    if not os.path.exists(csv_path):
        print("foods csv not found:", csv_path)
        return 0
    df = pd.read_csv(csv_path)
    cols = df.columns.tolist()
    conn = get_conn()
    cur = conn.cursor(cursor_factory=DictCursor)
    inserted = 0
    updated = 0
    for _, row in df.iterrows():
        name = row.get(cols[0])
        if pd.isna(name):
            continue
        name = str(name).strip()
        if not name:
            continue
        category = row.get(cols[1]) if len(cols) > 1 else None
        dosha = {}
        nutrients = {}
        notes = None
        for c in cols:
            v = row.get(c)
            if pd.isna(v):
                continue
            lc = c.lower()
            if 'vata' in lc or 'pitta' in lc or 'kapha' in lc:
                dosha[c] = _clean_value(v)
            elif 'note' in lc or 'digestion' in lc or 'effect' in lc:
                notes = _clean_value(v)
            elif any(k in lc for k in ['cal', 'protein', 'fat', 'carb', 'energy', 'calorie', 'mg', 'g']):
                nutrients[c] = _clean_value(v)
        raw = _clean_row_dict(row.to_dict())
        # check if exists by name (case-insensitive)
        cur.execute("SELECT id FROM food_items WHERE LOWER(name)=LOWER(%s) LIMIT 1;", (name,))
        found = cur.fetchone()
        if found:
            cur.execute("""
                UPDATE food_items SET category=%s, nutrients=%s, dosha_properties=%s, notes=%s, raw_row=%s
                WHERE id=%s
            """, (category, Json(nutrients), Json(dosha), notes, Json(raw), found['id']))
            updated += 1
        else:
            cur.execute("""
                INSERT INTO food_items (name, category, nutrients, dosha_properties, notes, raw_row)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (name, category, Json(nutrients), Json(dosha), notes, Json(raw)))
            inserted += 1
    conn.commit()
    cur.close()
    conn.close()
    print(f"foods inserted: {inserted}, updated: {updated}")
    return inserted + updated

def upsert_sources(csv_path):
    if not os.path.exists(csv_path):
        print("sources csv not found:", csv_path)
        return 0
    df = pd.read_csv(csv_path)
    conn = get_conn()
    cur = conn.cursor()
    inserted = 0
    updated = 0
    for _, r in df.iterrows():
        sid = r.get('source_id') or r.get('id') or None
        if sid is None or (isinstance(sid, float) and np.isnan(sid)):
            continue
        sid = str(sid)
        # check existence
        cur.execute("SELECT source_id FROM sources WHERE source_id=%s LIMIT 1;", (sid,))
        if cur.fetchone():
            cur.execute("""
              UPDATE sources SET title=%s, type=%s, language=%s, author=%s, publisher=%s, year=%s,
                                source_url=%s, license=%s, notes=%s
              WHERE source_id=%s
            """, (
                r.get('title'), r.get('type'), r.get('language'), r.get('author'),
                r.get('publisher'), r.get('year'), r.get('source_url'), r.get('license'),
                r.get('notes'), sid
            ))
            updated += 1
        else:
            cur.execute("""
              INSERT INTO sources (source_id,title,type,language,author,publisher,year,source_url,license,notes)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                sid, r.get('title'), r.get('type'), r.get('language'),
                r.get('author'), r.get('publisher'), r.get('year'),
                r.get('source_url'), r.get('license'), r.get('notes')
            ))
            inserted += 1
    conn.commit()
    cur.close()
    conn.close()
    print(f"sources inserted: {inserted}, updated: {updated}")
    return inserted + updated

if __name__ == "__main__":
    base = os.path.dirname(__file__)
    foods_csv = os.path.join(base, 'foods.csv')
    sources_csv = os.path.join(base, 'sources_bibliography.csv')
    n = upsert_foods(foods_csv)
    m = upsert_sources(sources_csv)
    print(f"foods rows processed: {n}")
    print(f"sources rows processed: {m}")
