# backend/app/run_sync_ingest_probe.py
import importlib, traceback, sys
from pathlib import Path

MODULE = "ingestion.pdf_loader"
UPSERT_MODULES = ["ingestion.upsert", "ingestion.upsert_documents", "ingestion.upsert_module"]
COMMON_LOADERS = [
    "pdf_to_documents", "load_pdf", "load_pdfs", "load_pdf_to_docs",
    "read_pdf", "read_pdf_documents", "extract_text_from_pdf",
    "parse_pdf", "load_document", "load_documents", "load_file"
]

def try_import(name):
    try:
        m = importlib.import_module(name)
        return m
    except Exception as e:
        print(f"Cannot import module {name}: {e}")
        return None

def list_module_attrs(m):
    try:
        names = sorted([n for n in dir(m) if not n.startswith("_")])
        print(f"\nModule {m.__name__} available attributes:\n", names)
    except Exception as e:
        print("Error listing attrs:", e)

def call_loader(m, func_name, path):
    try:
        func = getattr(m, func_name)
    except AttributeError:
        return None, f"Function {func_name} not present"
    try:
        print(f"\nTrying {m.__name__}.{func_name}('{path}') ...")
        res = func(path) if func.__code__.co_argcount <= 1 else func(path, lang="en")
        return res, None
    except TypeError as te:
        # try with kwargs fallback
        try:
            res = func(path, lang="en")
            return res, None
        except Exception as e:
            return None, f"Call error: {e}"
    except Exception as e:
        tb = traceback.format_exc()
        return None, f"Call raised exception: {e}\n{tb}"

def try_upsert(docs):
    upsert_mod = try_import("ingestion.upsert")
    if not upsert_mod:
        print("ingestion.upsert not found — skipping upsert attempt.")
        return
    # try common upsert function names
    for candidate in ("upsert_documents","upsert","upsert_docs","upsert_documents_batch"):
        if hasattr(upsert_mod, candidate):
            print(f"Found upsert function: ingestion.upsert.{candidate} — calling it...")
            func = getattr(upsert_mod, candidate)
            try:
                res = func(docs, source="local_sync", lang="en")
                print("Upsert returned:", res)
            except Exception as e:
                print("Upsert call failed:", e)
            return
    print("No upsert helper found in ingestion.upsert — please run DB upsert manually or paste ingestion.upsert.py file here for me to inspect.")

def main():
    p = Path("test_docs/sample.pdf")
    if not p.exists():
        print("File not found:", p.resolve())
        sys.exit(1)
    print("Using file:", p)

    m = try_import(MODULE)
    if not m:
        print("Cannot proceed without pdf_loader module. Please paste backend/app/ingestion/pdf_loader.py if issues persist.")
        sys.exit(1)

    list_module_attrs(m)

    # Try common loader function names
    for name in COMMON_LOADERS:
        res, err = call_loader(m, name, str(p))
        if err is None:
            print(f"\nSUCCESS: loader `{name}` returned a result of type {type(res)}")
            # print a small preview
            try:
                if isinstance(res, (list, tuple)):
                    print("Result is a list/tuple. len=", len(res))
                    for i, item in enumerate(res[:3]):
                        print(f"--- item {i} preview ---")
                        try:
                            # try to pretty-print if it looks like a dict/object
                            if hasattr(item, "to_dict"):
                                print(item.to_dict())
                            elif isinstance(item, dict):
                                from pprint import pprint
                                pprint(item)
                            else:
                                print(repr(item)[:1000])
                        except Exception as e:
                            print("Preview error:", e)
                else:
                    print("Result preview:", repr(res)[:1000])
            except Exception as e:
                print("Error previewing result:", e)

            # attempt upsert if we have a list
            if isinstance(res, (list, tuple)):
                try_upsert(res)
            else:
                print("Loader result not a list — not attempting upsert.")
            return

        else:
            print(f"Loader `{name}` not ok: {err}")

    print("\nNo common loader names worked. Paste the `backend/app/ingestion/pdf_loader.py` file contents here and I will craft the correct call.")

if __name__ == "__main__":
    main()
