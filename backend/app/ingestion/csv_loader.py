# backend/app/ingestion/csv_loader.py
import logging
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger("rag_app.csv_loader")

try:
    import pandas as pd  # type: ignore
    _has_pandas = True
except Exception:
    _has_pandas = False
    logger.warning("pandas not installed; csv_loader will not work without it. Install with `pip install pandas`.")


def _row_to_snippet(row, columns):
    parts = []
    for c in columns:
        val = row.get(c)
        if val is None or (isinstance(val, float) and str(val) == "nan"):
            continue
        s = f"{c}: {val}"
        parts.append(s)
    return "; ".join(parts)


def load_csv(path: str, encoding: Optional[str] = "utf-8", sep: Optional[str] = None, max_rows: Optional[int] = None) -> List[Dict]:
    """
    Load a CSV file and return a list of {'row_index': int, 'text': str}

    Parameters:
    - path: path to CSV file
    - encoding: file encoding (default utf-8)
    - sep: optional separator (auto-detected if None)
    - max_rows: optional limit to number of rows read (useful for very large files)

    Notes:
    - Uses pandas for robust parsing. Falls back to simple parsing if pandas not available.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    if not _has_pandas:
        # Lightweight fallback: naive parsing
        results = []
        with p.open("r", encoding=encoding, errors="ignore") as f:
            header = f.readline().strip().split(sep or ",")
            for i, line in enumerate(f):
                if max_rows and i >= max_rows:
                    break
                cols = line.strip().split(sep or ",")
                row = {}
                for j, col in enumerate(header):
                    row[col] = cols[j] if j < len(cols) else ""
                text = _row_to_snippet(row, header)
                results.append({"row_index": i, "text": text})
        return results

    # Use pandas
    df = pd.read_csv(p, encoding=encoding, sep=sep)
    if max_rows:
        df = df.head(max_rows)

    results = []
    for i, row in df.fillna("").iterrows():
        # Convert to dict and build snippet
        row_dict = {col: row[col] for col in df.columns}
        text = _row_to_snippet(row_dict, list(df.columns))
        results.append({"row_index": int(i), "text": text})
    logger.info("Loaded %d rows from CSV %s", len(results), path)
    return results


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python csv_loader.py <file.csv> [max_rows]")
        raise SystemExit(1)
    csv_path = sys.argv[1]
    max_rows = int(sys.argv[2]) if len(sys.argv) > 2 else None
    rows = load_csv(csv_path, max_rows=max_rows)
    print(f"Extracted {len(rows)} rows.")
    for r in rows[:3]:
        print(r)
