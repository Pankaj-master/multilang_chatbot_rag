const axios = require('axios');

async function embedTextWithGemini(text) {
  const url = process.env.GEMINI_EMBEDDING_URL || process.env.GEMINI_API_URL;
  if (!url) throw new Error('GEMINI_EMBEDDING_URL or GEMINI_API_URL not set');
  const apiKey = process.env.GEMINI_API_KEY;
  const resp = await axios.post(url, { input: text, type: 'embedding' }, {
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json'
    }
  });
  if (resp.data?.embedding) return resp.data.embedding;
  if (resp.data?.data?.[0]?.embedding) return resp.data.data[0].embedding;
  throw new Error('unexpected embedding response shape');
}

module.exports = { embedTextWithGemini };
