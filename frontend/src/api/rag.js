// frontend/src/api/rag.js
import axios from "axios";

const BACKEND = import.meta.env.VITE_BACKEND_URL || "http://localhost:8001";

const api = axios.create({
  baseURL: BACKEND,
  headers: { "Content-Type": "application/json" },
  timeout: 30_000,
});

export async function queryChat(query, lang = "en", history = []) {
  // Backend expects { message, language, history }
  const payload = { message: query, language: lang, history };
  const res = await api.post("/chat", payload);
  return res.data;
}

export default { queryChat };