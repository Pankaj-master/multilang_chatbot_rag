Node/Express backend (kept separate from the existing Python backend)

Setup
1. cd backend_node
2. cp .env.example .env and fill values
3. npm install
4. npm run dev

Notes
- Runs on port 8001 by default to avoid colliding with your Python backend.
- services/embeddings.js currently returns mocked retrievals; wire Pinecone/Weaviate when ready.
