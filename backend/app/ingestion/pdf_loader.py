# backend/app/ingestion/pdf_loader.py
import logging
from pathlib import Path
from typing import List, Dict
import io

logger = logging.getLogger("rag_app.pdf_loader")

try:
    import fitz  # PyMuPDF
    _has_fitz = True
except Exception:
    _has_fitz = False
    logger.warning("PyMuPDF (fitz) not installed; PDF loader will not work without it.")

# Optional OCR dependencies
try:
    from pdf2image import convert_from_path
    import pytesseract
    _has_ocr = True
except Exception:
    _has_ocr = False
    logger.debug("pdf2image or pytesseract not available; OCR fallback disabled.")


def _ocr_page_image(image) -> str:
    """
    Run OCR on a PIL Image or path-like image object using pytesseract.
    Returns extracted text.
    """
    try:
        text = pytesseract.image_to_string(image)
        return text or ""
    except Exception as e:
        logger.exception("OCR failed for page image: %s", e)
        return ""


def load_pdf(path: str, ocr_when_empty: bool = True, dpi: int = 200) -> List[Dict]:
    """
    Load PDF and return list of {'page': int, 'text': str}
    Uses PyMuPDF for text extraction. If a page is empty and OCR is available,
    it will render the page to an image and run pytesseract.

    Parameters:
    - path: path to the PDF file
    - ocr_when_empty: whether to run OCR on empty pages (requires pdf2image + pytesseract)
    - dpi: resolution for pdf2image when doing OCR

    Returns:
    - list of dicts with page number (1-indexed) and extracted text
    """
    if not _has_fitz:
        raise RuntimeError("PyMuPDF (fitz) is required for load_pdf. Install with `pip install pymupdf`.")

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"PDF file not found: {path}")

    doc = None
    results = []
    try:
        doc = fitz.open(str(p))
        for page_index in range(len(doc)):
            page = doc.load_page(page_index)
            text = page.get_text("text") or ""
            if not text.strip() and ocr_when_empty and _has_ocr:
                # Fallback to OCR for this page
                try:
                    # pdf2image uses 1-based page numbers
                    pil_images = convert_from_path(str(p), dpi=dpi, first_page=page_index + 1, last_page=page_index + 1)
                    ocr_text = []
                    for img in pil_images:
                        t = _ocr_page_image(img)
                        if t:
                            ocr_text.append(t)
                    text = "\n".join(ocr_text)
                except Exception as e:
                    logger.exception("pdf2image OCR conversion failed for page %d: %s", page_index + 1, e)
            results.append({"page": page_index + 1, "text": text})
    except Exception as e:
        logger.exception("Failed to load PDF %s: %s", path, e)
        raise
    finally:
        if doc:
            try:
                doc.close()
            except Exception:
                pass
    return results


if __name__ == "__main__":
    # quick test if run directly
    import sys
    if len(sys.argv) < 2:
        print("Usage: python pdf_loader.py <file.pdf>")
        sys.exit(1)
    pdf_path = sys.argv[1]
    pages = load_pdf(pdf_path)
    print(f"Loaded {len(pages)} pages from {pdf_path}")
    for p in pages[:3]:
        print("PAGE", p["page"], "chars:", len(p["text"]))
