const express = require('express');
const router = express.Router();
const axios = require('axios');
const { getPool } = require('../lib/db');

async function callRetriever(query, topK = 5) {
  const base = process.env.PY_RETRIEVER_URL_BASE || process.env.PY_RETRIEVER_URL || 'http://localhost:8000';
  const url = `${base.replace(/\/$/, '')}/api/retrieve`;
  try {
    const resp = await axios.get(url, { params: { q: query, k: topK }, timeout: 8000 });
    const data = resp.data;
    if (!data) return [];
    if (Array.isArray(data)) return data;
    if (data.results && Array.isArray(data.results)) return data.results;
    if (data.snippets && Array.isArray(data.snippets)) return data.snippets;
    if (data.chunks && Array.isArray(data.chunks)) return data.chunks;
    const arr = Object.values(data).find(v => Array.isArray(v));
    if (arr) return arr;
    return [data];
  } catch (err) {
    const status = err?.response?.status;
    const body = err?.response?.data;
    console.warn(`Retriever GET ${url} failed status=${status || 'ERR'} body=${JSON.stringify(body)}`);
    return [
      { id: 'fallback1', score: 0.9, text: 'Ash gourd (winter gourd) is a large vine-grown vegetable used in cooking and Ayurveda.' },
      { id: 'fallback2', score: 0.8, text: 'It is cooling, high in water content, and used to balance Pitta and Kapha.' }
    ].slice(0, topK);
  }
}

function extractSnippetText(item) {
  if (!item) return '';
  if (typeof item === 'string') return item;
  return item.text || item.chunk || item.content || item.body || item.passage || (item.metadata && (item.metadata.text || item.metadata.chunk)) || JSON.stringify(item).slice(0, 300);
}

// helper: safely extract text from possible Gemini content element
function extractTextFromContentElement(el) {
  if (!el) return '';
  // if element has parts array -> join text fields
  if (Array.isArray(el.parts)) {
    return el.parts.map(p => (p && (p.text || p))).filter(Boolean).join('');
  }
  // sometimes the element itself is a string
  if (typeof el === 'string') return el;
  // sometimes it's object with text
  if (typeof el === 'object') {
    if (el.text) return el.text;
    // nested parts under content.parts or similar
    if (Array.isArray(el.content)) {
      return el.content.map(c => extractTextFromContentElement(c)).join('');
    }
    // fallback: stringify small
    return JSON.stringify(el).slice(0, 1000);
  }
  return '';
}

async function callGeminiCompletion(promptOrMessages, maxTokens = 512) {
  const baseUrl = process.env.GEMINI_API_URL;
  if (!baseUrl) throw new Error('GEMINI_API_URL not set');
  const apiKey = process.env.GEMINI_API_KEY;
  const useChat = String(process.env.GEMINI_USE_CHAT || '').toLowerCase() === 'true';
  const isGoogleGen = baseUrl.includes('generativelanguage.googleapis.com') || baseUrl.includes('ai.google');

  if (isGoogleGen) {
    let model = (process.env.GEMINI_MODEL || 'gemini-2.5-flash').toString();
    model = model.replace(/^models\//, '');
    const url = baseUrl.replace(/\/$/, '') + `/v1beta/models/${model}:generateContent`;

    let contentsArray;
    if (useChat && Array.isArray(promptOrMessages)) {
      const joined = promptOrMessages.map(m => (m.content || m.text || '')).join('\n');
      contentsArray = [{ role: 'user', parts: [{ text: joined }] }];
    } else if (typeof promptOrMessages === 'string') {
      contentsArray = [{ role: 'user', parts: [{ text: promptOrMessages }] }];
    } else {
      const bodyText = JSON.stringify(promptOrMessages).slice(0, 64000);
      contentsArray = [{ role: 'user', parts: [{ text: bodyText }] }];
    }

    const body = {
      contents: contentsArray,
      generationConfig: {
        maxOutputTokens: maxTokens
      }
    };

    const headers = { 'Content-Type': 'application/json' };
    if (apiKey) headers['x-goog-api-key'] = apiKey;

    const resp = await axios.post(url, body, { headers, timeout: 30000 });
    return resp.data;
  }

  const payload = useChat
    ? { messages: promptOrMessages, max_tokens: maxTokens }
    : { prompt: promptOrMessages, max_tokens: maxTokens };

  const resp = await axios.post(baseUrl, payload, {
    headers: {
      Authorization: apiKey ? `Bearer ${apiKey}` : undefined,
      'Content-Type': 'application/json'
    },
    timeout: 30000
  });
  return resp.data;
}

router.post('/', async (req, res) => {
  const debugMode = (process.env.NODE_ENV || 'development') === 'development';
  try {
    const { user_id, text } = req.body;
    if (!text) return res.status(400).json({ error: 'no text' });

    const pool = getPool();
    await pool.query('INSERT INTO messages(user_id, role, text, created_at) VALUES($1,$2,$3,NOW())', [user_id || 'anon', 'user', text]);

    // retrieve context
    const retrieved = await callRetriever(text, 5);
    const snippetsArr = Array.isArray(retrieved) ? retrieved : [retrieved];
    const snippetsText = snippetsArr.map((s, i) => `S${i + 1}: ${extractSnippetText(s)}`).join('\n');

    // build prompt or messages depending on useChat
    const useChat = String(process.env.GEMINI_USE_CHAT || '').toLowerCase() === 'true';
    let geminiResp;
    if (useChat) {
      const messages = [
        { role: 'system', content: 'You are a helpful assistant.' },
        { role: 'user', content: `${snippetsText}\n\nUser question: ${text}` }
      ];
      geminiResp = await callGeminiCompletion(messages, 512);
    } else {
      const prompt = `You are an assistant. Use the retrieved snippets below to answer the user's question. If the snippets are insufficient, be explicit.\n\nRetrieved:\n${snippetsText}\n\nUser: ${text}\nAssistant:`;
      geminiResp = await callGeminiCompletion(prompt, 512);
    }

    // ---------- extract a clean text reply from various provider response shapes ----------
    let reply = '';

    try {
      // Google: candidates -> content (could be array or an object)
      if (geminiResp?.candidates?.[0]?.content) {
        const content = geminiResp.candidates[0].content;
        if (Array.isArray(content)) {
          reply = content.map(c => extractTextFromContentElement(c)).join('\n');
        } else {
          // content is likely an object with parts
          reply = extractTextFromContentElement(content);
        }
      }
      // Google new shape: response.output[0].content -> array of { text } or nested parts
      else if (geminiResp?.response?.output?.[0]?.content) {
        const c = geminiResp.response.output[0].content;
        if (Array.isArray(c)) {
          reply = c.map(x => (x.text || extractTextFromContentElement(x) || '')).join('');
        } else {
          reply = c.text || extractTextFromContentElement(c) || JSON.stringify(c);
        }
      }
      // OpenAI-like shapes
      else if (geminiResp?.choices?.[0]?.message?.content) {
        reply = geminiResp.choices[0].message.content;
      } else if (geminiResp?.choices?.[0]?.text) {
        reply = geminiResp.choices[0].text;
      }
      // other simple forms
      else if (typeof geminiResp === 'string') {
        reply = geminiResp;
      } else if (geminiResp?.output_text) {
        reply = geminiResp.output_text;
      } else {
        // deep search for the first string in the object
        const textCandidate = (function findText(obj) {
          if (!obj) return null;
          if (typeof obj === 'string') return obj;
          if (Array.isArray(obj)) {
            for (const el of obj) {
              const t = findText(el);
              if (t) return t;
            }
          } else if (typeof obj === 'object') {
            for (const k of Object.keys(obj)) {
              const t = findText(obj[k]);
              if (t) return t;
            }
          }
          return null;
        })(geminiResp);
        reply = textCandidate || JSON.stringify(geminiResp).slice(0, 2000);
      }
    } catch (ex) {
      console.warn('Reply extraction failed, falling back to stringification', ex);
      reply = JSON.stringify(geminiResp).slice(0, 2000);
    }

    // store assistant reply
    await pool.query('INSERT INTO messages(user_id, role, text, created_at) VALUES($1,$2,$3,NOW())', [user_id || 'anon', 'assistant', reply]);

    // respond (raw only in dev)
    const out = { reply };
    if (debugMode) out.raw = geminiResp;
    if (debugMode) out.retrieved = snippetsArr;
    res.json(out);

  } catch (err) {
    console.error('CHAT ERROR', err?.response?.data || err?.message || err);
    const debug = err?.response?.data ? err.response.data : (err?.message || String(err));
    if ((process.env.NODE_ENV || 'development') === 'development') {
      res.status(500).json({ error: 'internal', debug });
    } else {
      res.status(500).json({ error: 'internal' });
    }
  }
});

module.exports = router;
