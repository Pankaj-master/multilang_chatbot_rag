# backend/app/run_sync_ingest_full_fix2.py
"""
Synchronous ingest runner (fix for missing DEFAULT on pk column).

Behaviors:
 - Loads PDF via ingestion.pdf_loader.load_pdf(...)
 - Tries ingestion.upsert if present
 - Otherwise inserts into kb_documents and kb_chunks
 - If kb_documents PK has no default, the script will generate a PK:
     - integer-like -> SELECT COALESCE(MAX(pk),0)+1
     - otherwise -> uuid.uuid4().hex
Run from backend/app with venv active:
    python run_sync_ingest_full_fix2.py
"""
import os
import json
import traceback
from pathlib import Path

DB_DSN = os.environ.get("PG_DSN", "postgresql://postgres:postgres@localhost:5432/rag_db")
PDF_PATH = Path("test_docs/sample.pdf")

def try_import(name):
    try:
        mod = __import__(name, fromlist=["*"])
        return mod
    except Exception:
        return None

def insert_via_upsert_module(docs):
    upsert_mod = try_import("ingestion.upsert")
    if not upsert_mod:
        print("ingestion.upsert module not found.")
        return False

    for fn_name in ("upsert_documents","upsert","upsert_docs","upsert_documents_batch"):
        func = getattr(upsert_mod, fn_name, None)
        if callable(func):
            print(f"Calling ingestion.upsert.{fn_name}(...).")
            try:
                res = func(docs, source="local_sync", lang="en")
                print("ingestion.upsert returned:", res)
                return True
            except Exception:
                print("ingestion.upsert call raised an exception:")
                traceback.print_exc()
                return False

    print("No suitable upsert function found in ingestion.upsert.")
    return False

def pg_connect():
    import psycopg2
    conn = psycopg2.connect(DB_DSN)
    return conn

def discover_table_columns(conn, table_name):
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """, (table_name,))
    cols = [r[0] for r in cur.fetchall()]
    cur.close()
    return cols

def get_column_info(conn, table_name, column_name):
    """Return (data_type, column_default)"""
    cur = conn.cursor()
    cur.execute("""
        SELECT data_type, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
        """, (table_name, column_name))
    row = cur.fetchone()
    cur.close()
    return row if row else (None, None)

def detect_pk_column(cols):
    # common PK names
    for candidate in ("id", "doc_id", "document_id", "kb_documents_id", "kb_id"):
        if candidate in cols:
            return candidate
    # fallback: first column
    if cols:
        return cols[0]
    return None

def generate_pk_value(conn, pk_col):
    """Generate a pk value when column has no DEFAULT.
    If integer-like -> choose MAX(pk)+1
    Else -> generate uuid hex string.
    """
    import uuid
    cur = conn.cursor()
    # inspect data_type
    cur.execute("""
        SELECT data_type
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name='kb_documents' AND column_name=%s
    """, (pk_col,))
    row = cur.fetchone()
    data_type = row[0] if row else None
    data_type = (data_type or "").lower()
    if "int" in data_type:
        # compute next integer id (simple approach)
        cur.execute(f"SELECT COALESCE(MAX({pk_col}), 0) + 1 FROM kb_documents;")
        next_id = cur.fetchone()[0]
        cur.close()
        print(f"Generated integer PK {pk_col} = {next_id}")
        return next_id
    else:
        # generate UUID hex (string)
        val = uuid.uuid4().hex
        cur.close()
        print(f"Generated UUID PK {pk_col} = {val}")
        return val

def safe_insert_document_and_chunks(conn, filename, pages):
    """
    Insert document row into kb_documents and insert page-chunks into kb_chunks.
    Adapts to discovered column names and uses correct PK handling.
    """
    cur = conn.cursor()
    kb_doc_cols = discover_table_columns(conn, "kb_documents")
    kb_chunk_cols = discover_table_columns(conn, "kb_chunks")
    print("kb_documents columns discovered:", kb_doc_cols)
    print("kb_chunks columns discovered:", kb_chunk_cols)

    pk_col = detect_pk_column(kb_doc_cols)
    print("Detected kb_documents PK column:", pk_col)

    # check if pk has a default
    data_type, column_default = get_column_info(conn, "kb_documents", pk_col)
    print("PK column data_type:", data_type, "column_default:", column_default)

    # Prepare document payload
    metadata = {"source": "local_sync", "ingested_from": str(filename)}
    doc_insert_cols = []
    doc_insert_vals = []
    if "filename" in kb_doc_cols:
        doc_insert_cols.append("filename"); doc_insert_vals.append(str(filename.name))
    if "source" in kb_doc_cols:
        doc_insert_cols.append("source"); doc_insert_vals.append("local_sync")
    if "source_type" in kb_doc_cols and "source" not in doc_insert_cols:
        doc_insert_cols.append("source_type"); doc_insert_vals.append("local_sync")
    if "source_path" in kb_doc_cols:
        doc_insert_cols.append("source_path"); doc_insert_vals.append(str(filename))
    if "title" in kb_doc_cols:
        doc_insert_cols.append("title"); doc_insert_vals.append(str(filename.name))
    if "metadata" in kb_doc_cols:
        doc_insert_cols.append("metadata"); doc_insert_vals.append(json.dumps(metadata))
    if "content" in kb_doc_cols and isinstance(pages, list):
        joined = "\n\n".join(p.get("text","") for p in pages)
        doc_insert_cols.append("content"); doc_insert_vals.append(joined[:100000])

    # If PK has no default, ensure we include the PK column in insert with a generated value
    include_pk = False
    pk_value = None
    if column_default is None:
        # need to generate pk value and include pk_col in insert
        pk_value = generate_pk_value(conn, pk_col)
        include_pk = True
        doc_insert_cols.insert(0, pk_col)
        doc_insert_vals.insert(0, pk_value)

    if not doc_insert_cols:
        raise RuntimeError("No suitable columns to insert into kb_documents (checked filename/source/title/metadata/content).")

    placeholders = ",".join(["%s"] * len(doc_insert_vals))
    cols_sql = ",".join(doc_insert_cols)

    # Use RETURNING on pk_col
    returning_col = pk_col or "id"
    insert_sql = f"INSERT INTO kb_documents ({cols_sql}) VALUES ({placeholders}) RETURNING {returning_col};"
    print("Document INSERT SQL:", insert_sql)
    cur.execute(insert_sql, tuple(doc_insert_vals))
    doc_id = cur.fetchone()[0]
    print(f"Inserted kb_documents {returning_col}:", doc_id)

    # Determine chunk fk column on kb_chunks
    fk_col = None
    for c in ("doc_id", "document_id", "docid", "doc_pk", pk_col):
        if c and c in kb_chunk_cols:
            fk_col = c
            break
    print("Using kb_chunks foreign-key column:", fk_col)

    # Insert chunks
    chunk_rows = 0
    for page in pages:
        page_num = page.get("page")
        text = page.get("text","").strip()
        if not text:
            continue
        chunk_insert_cols = []
        chunk_insert_vals = []
        if fk_col:
            chunk_insert_cols.append(fk_col); chunk_insert_vals.append(doc_id)
        if "page" in kb_chunk_cols:
            chunk_insert_cols.append("page"); chunk_insert_vals.append(page_num)
        if "text" in kb_chunk_cols:
            chunk_insert_cols.append("text"); chunk_insert_vals.append(text[:100000])
        elif "content" in kb_chunk_cols:
            chunk_insert_cols.append("content"); chunk_insert_vals.append(text[:100000])
        elif "text_snippet" in kb_chunk_cols:
            chunk_insert_cols.append("text_snippet"); chunk_insert_vals.append(text[:100000])
        elif "chunk" in kb_chunk_cols:
            chunk_insert_cols.append("chunk"); chunk_insert_vals.append(text[:100000])

        if "language" in kb_chunk_cols:
            chunk_insert_cols.append("language"); chunk_insert_vals.append("en")
        if "row_index" in kb_chunk_cols and "chunk_index" in kb_chunk_cols:
            chunk_insert_cols.append("row_index"); chunk_insert_vals.append(page_num)
            chunk_insert_cols.append("chunk_index"); chunk_insert_vals.append(0)

        if not chunk_insert_cols:
            continue

        placeholders = ",".join(["%s"] * len(chunk_insert_vals))
        cols_sql = ",".join(chunk_insert_cols)
        insert_sql = f"INSERT INTO kb_chunks ({cols_sql}) VALUES ({placeholders});"
        cur.execute(insert_sql, tuple(chunk_insert_vals))
        chunk_rows += 1

    conn.commit()
    cur.close()
    print(f"Inserted {chunk_rows} kb_chunks for document {returning_col}={doc_id}")
    return doc_id, chunk_rows

def main():
    if not PDF_PATH.exists():
        print("PDF not found at:", PDF_PATH.resolve())
        return

    print("Loading PDF via ingestion.pdf_loader.load_pdf(...)")
    pdf_loader = try_import("ingestion.pdf_loader")
    if not pdf_loader:
        print("ingestion.pdf_loader not importable. Aborting.")
        return

    try:
        pages = pdf_loader.load_pdf(str(PDF_PATH), ocr_when_empty=True, dpi=200)
    except Exception:
        print("pdf_loader.load_pdf raised exception:")
        traceback.print_exc()
        return

    print("Extracted pages:", len(pages))
    normalized = []
    for p in pages:
        if isinstance(p, dict):
            normalized.append({"page": p.get("page"), "text": p.get("text","")})
        else:
            normalized.append({"page": None, "text": str(p)})

    try:
        ok = insert_via_upsert_module(normalized)
        if ok:
            print("Upsert module handled insertion. Done.")
            return
    except Exception:
        print("ingestion.upsert attempt failed:")
        traceback.print_exc()

    # fallback to direct DB insertion
    try:
        conn = pg_connect()
        doc_id, chunk_count = safe_insert_document_and_chunks(conn, PDF_PATH, normalized)
        print("Synchronous ingestion complete. doc_id:", doc_id, "chunks:", chunk_count)
        conn.close()
    except Exception:
        print("Direct DB insertion failed:")
        traceback.print_exc()

if __name__ == "__main__":
    main()
