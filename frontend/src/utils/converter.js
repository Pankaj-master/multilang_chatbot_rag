// frontend/src/utils/converters.js
// Small helpers to normalize backend data into UI-friendly shapes.

export function safeTrim(s) {
  if (s === null || s === undefined) return '';
  if (typeof s === 'string') return s.trim();
  return String(s);
}

/**
 * Convert knowledge-base / ingestion items into UI cards for the Carousel/ImageCard.
 * Expects items to be an array of objects that may contain:
 *  - title, name
 *  - snippet, text_snippet, description, desc
 *  - image, image_url, thumbnail
 *  - url, link
 *
 * Returns array of { title, description, image, action }
 */
export function toCardsFromKB(items = []) {
  if (!Array.isArray(items)) return [];

  return items.map((it) => {
    const title = safeTrim(it.title || it.name || it.doc_id || '');
    const description = safeTrim(it.description || it.desc || it.snippet || it.text_snippet || '');
    const image =
      it.image ||
      it.image_url ||
      it.thumbnail ||
      (it.metadata && (it.metadata.image || it.metadata.image_url)) ||
      null;

    const action = it.action || (it.url ? { url: it.url, label: 'Learn more' } : null);

    return {
      title,
      description,
      image,
      action,
      raw: it, // keep original for debugging or detail views
    };
  });
}

/**
 * Convert backend card/item shape to the minimal UI card shape.
 * Accepts either a single item or an array.
 */
export function normalizeCards(input) {
  if (!input) return [];
  if (Array.isArray(input)) return toCardsFromKB(input);
  return toCardsFromKB([input]);
}
