# backend/app/api/retrieval_api.py
''' chroma from fastapi import APIRouter
from backend.app.retriever_chroma import retrieve

router = APIRouter()

@router.get("/retrieve")
async def retrieve_endpoint(q: str, k: int = 5):
    items = retrieve(q, top_k=k)
    return {"query": q, "results": items}'''
# backend/app/api/retrieval_api.py
from fastapi import APIRouter
from app.retriever_faiss import retrieve

router = APIRouter()

@router.get("/retrieve")
async def retrieve_endpoint(q: str, k: int = 5):
    items = retrieve(q, top_k=k)
    return {"query": q, "results": items}


