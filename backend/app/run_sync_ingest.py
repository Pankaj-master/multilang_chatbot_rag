# backend/app/run_sync_ingest.py
import os
from pathlib import Path

try:
    from ingestion.ingest import ingest_file_sync
except Exception:
    ingest_file_sync = None

def fallback_ingest(pdf_path, lang="en"):
    from ingestion.pdf_loader import pdf_to_documents
    from ingestion.upsert import upsert_documents

    docs = pdf_to_documents(pdf_path, lang=lang)
    print(f"Extracted {len(docs)} documents")
    res = upsert_documents(docs, source="local_sync", lang=lang)
    print("Upsert result:", res)
    return res

def main():
    p = Path("test_docs/sample.pdf")
    if not p.exists():
        print("File not found:", p.resolve())
        return

    print("Running sync ingestion...")
    if ingest_file_sync:
        r = ingest_file_sync(str(p), lang="en")
        print("Ingest result:", r)
    else:
        r = fallback_ingest(str(p), lang="en")
        print("Fallback result:", r)

if __name__ == "__main__":
    main()