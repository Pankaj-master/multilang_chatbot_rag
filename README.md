# Multilang Chatbot (RAG) — Quickstart

This repository contains a RAG-based multilingual chatbot:
- Backend: FastAPI (ingestion, retrieval, embeddings, LLM wrapper)
- Frontend: React + Vite + Tailwind
- Storage: Postgres (kb_documents, kb_chunks), Redis (cache), optional Pinecone

This README gives local dev steps, Docker Compose, and Windows-specific tips.

---

## Prerequisites

- Docker & Docker Compose (recommended for quick local dev)
- Or: Python 3.10 (recommended) + Node 18, Postgres, Redis locally
- Optional: Miniconda/Anaconda for easier Python env management

---

## Quickstart with Docker Compose (recommended)

From repo root:

```bash
docker compose up --build