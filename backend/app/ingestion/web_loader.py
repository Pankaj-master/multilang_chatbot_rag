# backend/app/ingestion/web_loader.py
import logging
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

logger = logging.getLogger("rag_app.web_loader")

try:
    import requests  # type: ignore
    from bs4 import BeautifulSoup  # type: ignore
    _has_requests = True
except Exception:
    _has_requests = False
    logger.error("requests and BeautifulSoup are required for web_loader. Install with `pip install requests beautifulsoup4`.")

# Optional Playwright fallback for JS-heavy pages
_try_playwright = False
try:
    from playwright.sync_api import sync_playwright  # type: ignore
    _has_playwright = True
except Exception:
    _has_playwright = False
    logger.debug("playwright not installed; JS-heavy page fallback disabled.")


USER_AGENT = "warp-multilang-rag-bot/1.0 (+https://example.com/contact)"

def _clean_soup(soup: BeautifulSoup):
    # Remove scripts, styles, nav, footer, noscript
    for tag in soup(["script", "style", "header", "footer", "nav", "noscript", "iframe", "svg"]):
        try:
            tag.decompose()
        except Exception:
            pass
    return soup

def _extract_visible_text(soup: BeautifulSoup) -> str:
    """
    Extract visible text by concatenating paragraphs, headings, list items and figcaptions.
    """
    parts: List[str] = []

    # Headings
    for h in soup.find_all(["h1", "h2", "h3", "h4", "h5"]):
        text = h.get_text(separator=" ", strip=True)
        if text:
            parts.append(text)

    # Paragraphs
    for p in soup.find_all("p"):
        text = p.get_text(separator=" ", strip=True)
        if text:
            parts.append(text)

    # List items
    for li in soup.find_all("li"):
        text = li.get_text(separator=" ", strip=True)
        if text:
            parts.append(text)

    # Figure captions
    for fc in soup.find_all("figcaption"):
        text = fc.get_text(separator=" ", strip=True)
        if text:
            parts.append(text)

    # Meta description as fallback
    meta_desc = ""
    tag = soup.find("meta", attrs={"name": "description"})
    if tag and tag.get("content"):
        meta_desc = tag["content"].strip()
    if meta_desc:
        parts.insert(0, meta_desc)

    # Join parts intelligently, limit repeated whitespace
    content = "\n\n".join(parts)
    return content.strip()


def _extract_images(soup: BeautifulSoup, base_url: str) -> List[Dict]:
    """
    Extract candidate image URLs with alt text and caption (if available).
    Returns list of dicts: {"url", "alt", "caption"}
    """
    images = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src:
            continue
        # Resolve relative URLs
        try:
            full_url = urljoin(base_url, src)
        except Exception:
            full_url = src
        alt = (img.get("alt") or "").strip()
        caption = None
        parent = img.parent
        if parent:
            figcap = parent.find("figcaption")
            if figcap:
                caption = figcap.get_text(separator=" ", strip=True)
        images.append({"url": full_url, "alt": alt, "caption": caption})
    # Deduplicate while preserving order
    seen = set()
    unique_images = []
    for im in images:
        if im["url"] in seen:
            continue
        seen.add(im["url"])
        unique_images.append(im)
    return unique_images


def _requests_get_text(url: str, timeout: int = 15, headers: Optional[Dict] = None) -> Dict:
    headers = headers or {"User-Agent": USER_AGENT}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    # Respect response encoding if provided
    resp.encoding = resp.apparent_encoding or resp.encoding
    html = resp.text
    return {"status_code": resp.status_code, "html": html, "final_url": resp.url, "headers": dict(resp.headers)}


def _playwright_get_text(url: str, timeout: int = 30) -> Dict:
    """
    Use Playwright to render JS-heavy pages. Synchronous Playwright usage.
    Caller must ensure Playwright is installed and browsers are installed (playwright install).
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_navigation_timeout(timeout * 1000)
        page.goto(url, wait_until="networkidle")
        html = page.content()
        final_url = page.url
        # try to capture response code via main resource
        try:
            resp = page.request
        except Exception:
            resp = None
        browser.close()
    return {"status_code": 200, "html": html, "final_url": final_url, "headers": {}}


def load_url(url: str, timeout: int = 15, use_playwright_if_no_text: bool = True, headers: Optional[Dict] = None) -> Dict:
    """
    Fetch and extract text and metadata from `url`.
    Returns:
      {
        "url": final_url,
        "title": title,
        "text": extracted_text,
        "html": html,
        "images": [{"url","alt","caption"}, ...],
        "meta": {"description":..., "keywords":..., ...}
      }

    - If the page is JS-heavy and yields no text, you may opt-in to Playwright fallback by setting use_playwright_if_no_text=True.
    """
    if not _has_requests:
        raise RuntimeError("requests + beautifulsoup4 are required for load_url. Install with `pip install requests beautifulsoup4`.")

    try:
        resp = _requests_get_text(url, timeout=timeout, headers=headers)
        html = resp.get("html", "")
        final_url = resp.get("final_url", url)
    except Exception as e:
        logger.warning("requests failed for URL %s: %s", url, e)
        # Optionally try Playwright if available
        if _has_playwright and use_playwright_if_no_text:
            try:
                logger.info("Falling back to Playwright for URL %s", url)
                resp = _playwright_get_text(url, timeout=max(timeout, 30))
                html = resp.get("html", "")
                final_url = resp.get("final_url", url)
            except Exception as e2:
                logger.exception("Playwright fallback failed for URL %s: %s", url, e2)
                return {"url": url, "title": "", "text": "", "html": "", "images": [], "meta": {}}
        else:
            return {"url": url, "title": "", "text": "", "html": "", "images": [], "meta": {}}

    # parse HTML
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        logger.exception("BeautifulSoup parsing failed for URL %s: %s", final_url, e)
        return {"url": final_url, "title": "", "text": "", "html": html, "images": [], "meta": {}}

    soup = _clean_soup(soup)
    title_tag = soup.title.string.strip() if soup.title and soup.title.string else ""
    text = _extract_visible_text(soup)
    images = _extract_images(soup, base_url=final_url)

    # meta tags
    meta = {}
    try:
        description_tag = soup.find("meta", attrs={"name": "description"})
        if description_tag and description_tag.get("content"):
            meta["description"] = description_tag["content"].strip()
        keywords_tag = soup.find("meta", attrs={"name": "keywords"})
        if keywords_tag and keywords_tag.get("content"):
            meta["keywords"] = keywords_tag["content"].strip()
        # OG tags
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            meta["og:title"] = og_title.get("content").strip()
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            meta["og:description"] = og_desc.get("content").strip()
    except Exception:
        pass

    return {
        "url": final_url,
        "title": title_tag or meta.get("og:title") or final_url,
        "text": text,
        "html": html,
        "images": images,
        "meta": meta,
    }


if __name__ == "__main__":
    # quick manual test
    test_url = "https://en.wikipedia.org/wiki/Mung_bean"
    out = load_url(test_url)
    print("Title:", out["title"])
    print("Chars:", len(out["text"]))
    print("Images:", len(out["images"]))
