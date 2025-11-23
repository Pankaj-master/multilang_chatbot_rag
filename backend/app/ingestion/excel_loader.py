# backend/app/ingestion/excel_loader.py
import logging
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger("rag_app.excel_loader")

try:
    import pandas as pd
    _has_pandas = True
except Exception:
    _has_pandas = False
    logger.warning("pandas not installed; excel_loader will not function. Install via `pip install pandas openpyxl`.")


def _row_to_snippet(row, columns):
    """
    Convert a row dict to a semicolon-separated text snippet.
    Example: "Name: Wheat; Calories: 364; Protein: 12.2"
    """
    parts = []
    for c in columns:
        val = row.get(c)
        if val is None or (isinstance(val, float) and str(val) == "nan"):
            continue
        parts.append(f"{c}: {val}")
    return "; ".join(parts)


def load_excel(path: str, sheet_name: Optional[str] = None, max_rows: Optional[int] = None) -> List[Dict]:
    """
    Load an Excel file (xls/xlsx) and convert each row into a text snippet for ingestion.

    Returns:
        List of {"row_index": int, "text": str}
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Excel file not found: {path}")

    if not _has_pandas:
        raise RuntimeError("pandas not installed. Install via `pip install pandas openpyxl`.")

    try:
        df = pd.read_excel(p, sheet_name=sheet_name)
    except Exception as e:
        logger.exception("Failed to read Excel %s: %s", path, e)
        raise

    if max_rows:
        df = df.head(max_rows)

    df = df.fillna("")
    columns = list(df.columns)

    results = []
    for i, row in df.iterrows():
        row_dict = {col: row[col] for col in columns}
        text = _row_to_snippet(row_dict, columns)
        results.append({"row_index": int(i), "text": text})

    logger.info("Loaded %d rows from Excel %s", len(results), path)
    return results


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python excel_loader.py <file.xlsx>")
        raise SystemExit(1)
    excel_path = sys.argv[1]
    rows = load_excel(excel_path)
    print(f"Extracted {len(rows)} rows.")
    for r in rows[:3]:
        print(r)
