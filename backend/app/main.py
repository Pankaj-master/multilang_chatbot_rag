# backend/app/main.py
from fastapi import FastAPI
import uvicorn
from app.api.health import router as health_router
from app.api.retrieval_api import router as retrieval_router

app = FastAPI(title="multilang-rag")
app.include_router(health_router, prefix="/api")
app.include_router(retrieval_router, prefix="/api")

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=3000, reload=True)
