# backend/app/routes/health.py
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from datetime import datetime
import os
import platform
import logging

logger = logging.getLogger("rag_app.health")

router = APIRouter()

@router.get("/live", summary="Liveness probe")
async def liveness():
    """
    Simple liveness endpoint.
    Returns 200 if the service process is running.
    """
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "ok",
            "time": datetime.utcnow().isoformat() + "Z",
            "service": "multilang_chatbot_rag",
        },
    )

@router.get("/ready", summary="Readiness probe")
async def readiness():
    """
    Basic readiness check. Extend this to check DB, cache, and vector DB readiness.
    Currently returns OK; in future hook in health checks for Postgres/Pinecone/Redis/LLM.
    """
    # Placeholder for real dependency checks (DB, cache, vector db, llm)
    dependencies = {
        "postgres": os.getenv("DB_URL", "not-configured"),
        "vector_db": os.getenv("PINECONE_INDEX", os.getenv("PINECONE_API_KEY") and "configured" or "not-configured"),
        "llm_api": os.getenv("LLM_API", "not-configured"),
    }

    logger.debug("Readiness check dependencies: %s", dependencies)

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "ready",
            "time": datetime.utcnow().isoformat() + "Z",
            "service": "multilang_chatbot_rag",
            "dependencies": dependencies,
        },
    )
