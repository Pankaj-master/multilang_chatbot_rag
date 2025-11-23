export function parseResponse(data) {
  if (!data || typeof data !== 'object') {
    return { answer: '', cards: [] }
  }

  // Main text or fallback fields
  const answer =
    data.answer ||
    data.text ||
    (data.output && data.output.text) ||
    ''

  // Normalize cards / carousel items
  let cards = []

  if (Array.isArray(data.cards)) {
    cards = data.cards
  } else if (Array.isArray(data.items)) {
    cards = data.items
  } else if (data.carousel && Array.isArray(data.carousel.items)) {
    cards = data.carousel.items
  }

  // Ensure consistent item shape
  cards = cards.map(item => ({
    title: item.title || '',
    description: item.description || '',
    image: item.image || null,
    action: item.action || null
  }))

  return { answer, cards }
}

// For ChatInterface.jsx — merges old messages and backend response
export function buildMessageObject(userMessage, backend) {
  return {
    user: userMessage,
    bot: backend.answer,
    cards: backend.cards || []
  }
}
