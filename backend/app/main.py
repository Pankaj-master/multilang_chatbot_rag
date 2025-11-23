# backend/app/main.py
import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables from .env file
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# initialize logging first
from .utils.logging_utils import init_logging, get_logger, fastapi_logging_middleware

init_logging()
logger = get_logger("rag_app.main")

# Import routers
try:
    from .routes.chat import router as chat_router
except Exception as e:
    logger.warning("Could not import chat router: %s", e)
    chat_router = None

try:
    from .routes.ingest import router as ingest_router
except Exception as e:
    logger.warning("Could not import ingest router: %s", e)
    ingest_router = None

try:
    from .routes.health import router as health_router
except Exception as e:
    logger.warning("Could not import health router: %s", e)
    health_router = None

# DB startup/shutdown helpers
try:
    from .services.db import startup as db_startup, shutdown as db_shutdown
except Exception:
    db_startup = None
    db_shutdown = None
    logger.warning("DB startup/shutdown helpers not available; ensure services/db.py exists.")

# Optionally initialize cache (best-effort)
try:
    # we only import to let redis lazy-init when used
    from .services import cache as cache_module  # noqa: F401
except Exception:
    logger.debug("Cache module not available or failed to import (optional).")

# Create FastAPI app
app = FastAPI(
    title=os.getenv("APP_TITLE", "Multilang RAG Chatbot"),
    version=os.getenv("APP_VERSION", "0.1.0"),
    description="RAG-based chatbot for nutrition knowledge base (PDF/CSV/URLs).",
)

# CORS
origins_env = os.getenv("CORS_ORIGINS", "")
if origins_env:
    origins = [o.strip() for o in origins_env.split(",") if o.strip()]
else:
    origins = ["*"] if os.getenv("ENV", "dev") == "dev" else []

if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.info("CORS configured for origins: %s", origins)

# Attach simple request logging middleware
app.middleware("http")(fastapi_logging_middleware)


# Include routers (if available)
if chat_router:
    app.include_router(chat_router, prefix="/chat", tags=["chat"])
    logger.info("Mounted /chat router.")

if ingest_router:
    app.include_router(ingest_router, prefix="/ingest", tags=["ingest"])
    logger.info("Mounted /ingest router.")

if health_router:
    app.include_router(health_router, prefix="/health", tags=["health"])
    logger.info("Mounted /health router.")


# Readiness endpoint (simple)
@app.get("/ready", tags=["health"])
async def ready():
    """
    Readiness probe: returns {"ok": True} when the app is up.
    It does not check external services (use /health for deeper checks).
    """
    return {"ok": True}


# Startup & shutdown events
@app.on_event("startup")
async def on_startup():
    logger.info("Application startup: initializing resources...")
    # DB pool init
    if db_startup:
        try:
            await db_startup()
            logger.info("Database pool initialized.")
        except Exception as e:
            logger.exception("Database startup failed: %s", e)

    # Additional warmups (optional): preload sentence-transformers small model? left to services
    logger.info("Startup complete.")


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("Application shutdown: closing resources...")
    if db_shutdown:
        try:
            await db_shutdown()
            logger.info("Database pool closed.")
        except Exception as e:
            logger.exception("Database shutdown failed: %s", e)
    logger.info("Shutdown complete.")


# Run with `python -m backend.app.main` or `python backend/app/main.py`
if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload_flag = os.getenv("DEV_RELOAD", "true").lower() in ("1", "true", "yes")

    logger.info("Starting Uvicorn on %s:%d (reload=%s)", host, port, reload_flag)
    uvicorn.run("backend.app.main:app", host=host, port=port, reload=reload_flag, log_level="info")
