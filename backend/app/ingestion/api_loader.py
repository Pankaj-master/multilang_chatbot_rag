# backend/app/ingestion/api_loader.py
import logging
import json
from typing import Dict, Any, Optional
from urllib.parse import urlencode, urljoin

logger = logging.getLogger("rag_app.api_loader")

try:
    import requests  # type: ignore
    _has_requests = True
except Exception:
    _has_requests = False
    logger.error("requests not installed. Install with `pip install requests`.")


def _flatten_json(obj: Any, parent_key: str = "") -> str:
    """
    Convert nested JSON to a readable text format:
    Example:
        {"name": "Wheat", "nutrients": {"calories": 364, "protein": 12.2}}
    =>
        "name: Wheat\nnutrients.calories: 364\nnutrients.protein: 12.2"
    """
    lines = []

    def recurse(v, k):
        if isinstance(v, dict):
            for sub_k, sub_v in v.items():
                recurse(sub_v, f"{k}.{sub_k}" if k else sub_k)
        elif isinstance(v, list):
            for i, item in enumerate(v):
                recurse(item, f"{k}[{i}]")
        else:
            lines.append(f"{k}: {v}")

    recurse(obj, parent_key)
    return "\n".join(lines)


def _safe_get_json(url: str, headers: Optional[Dict] = None, params: Optional[Dict] = None, timeout: int = 15) -> Dict:
    """GET request and return parsed JSON safely."""
    if not _has_requests:
        raise RuntimeError("requests not installed.")

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=timeout)
        resp.raise_for_status()
    except Exception as e:
        logger.exception("API request failed for %s: %s", url, e)
        return {"ok": False, "json": None, "status": None, "url": url}

    try:
        data = resp.json()
    except Exception:
        logger.warning("Response not JSON from %s, returning raw text.", url)
        data = {"raw_text": resp.text}

    return {"ok": True, "json": data, "status": resp.status_code, "url": resp.url}


def _extract_next_page(data: Any, url: str) -> Optional[str]:
    """
    Auto-detect next URL for common pagination patterns.
    Supports:
      - data["next"] (Django REST)
      - data["links"]["next"] (GitHub, some APIs)
      - data["pagination"]["next_page"]
    """
    if isinstance(data, dict):
        # pattern 1
        nxt = data.get("next")
        if isinstance(nxt, str):
            return urljoin(url, nxt)

        # pattern 2
        links = data.get("links")
        if links and isinstance(links, dict) and isinstance(links.get("next"), str):
            return urljoin(url, links["next"])

        # pattern 3
        pag = data.get("pagination")
        if pag and isinstance(pag, dict) and pag.get("next_page"):
            nxt = pag["next_page"]
            if isinstance(nxt, str):
                return urljoin(url, nxt)

    return None


def load_api(
    url: str,
    headers: Optional[Dict] = None,
    params: Optional[Dict] = None,
    paginate: bool = False,
    max_pages: int = 3,
) -> Dict:
    """
    Fetch and flatten JSON from an API endpoint.

    Returns:
        {
          "title": "<API Title or URL>",
          "text": "<flattened multiline text>",
          "json": <raw full json>,
          "url": "<final URL>"
        }
    """
    all_json_pages = []
    all_text_parts = []

    current_url = url
    current_params = params or {}

    for page in range(max_pages if paginate else 1):
        resp = _safe_get_json(current_url, headers=headers, params=current_params)

        if not resp["ok"]:
            break

        data = resp["json"]
        all_json_pages.append(data)

        # flatten JSON → text
        flat_text = _flatten_json(data)
        all_text_parts.append(flat_text)

        # stop if no pagination needed
        if not paginate:
            break

        next_url = _extract_next_page(data, current_url)
        if not next_url:
            break

        current_url = next_url
        current_params = {}  # next link already contains params

    combined_text = "\n\n".join(all_text_parts)
    final_json = {"pages": all_json_pages}

    logger.info("API loader fetched %d page(s) from %s", len(all_json_pages), url)

    return {
        "title": f"API: {url}",
        "text": combined_text,
        "json": final_json,
        "url": url,
    }


if __name__ == "__main__":
    # quick manual test
    test_url = "https://api.github.com/repos/python/cpython"
    out = load_api(test_url)
    print("Title:", out["title"])
    print("Text sample:", out["text"][:300])
