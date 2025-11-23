# backend/app/utils/logging_utils.py
"""
Central logging utility for the RAG backend.

Features:
 - Color-coded console logs
 - Rotating file logs (rag_app.log)
 - JSON log mode (for production / cloud logging)
 - Safe get_logger(name) helper for all modules
 - Optional FastAPI middleware to log requests/responses

Usage:
    from backend.app.utils.logging_utils import init_logging, get_logger
    logger = get_logger("rag_app.retriever")
    logger.info("message")
"""

import os
import sys
import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from typing import Optional

# ---------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_JSON = os.getenv("LOG_JSON", "false").lower() == "true"
LOG_FILE = os.getenv("LOG_FILE", "rag_app.log")
LOG_MAX_MB = int(os.getenv("LOG_MAX_MB", "5"))  # rollover every 5 MB
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "3"))


# ---------------------------------------------------------
# Color formatting for console logs
# ---------------------------------------------------------
class ColorFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[96m",   # cyan
        "INFO": "\033[92m",    # green
        "WARNING": "\033[93m", # yellow
        "ERROR": "\033[91m",   # red
        "CRITICAL": "\033[95m" # magenta
    }
    RESET = "\033[0m"

    def format(self, record):
        level_color = self.COLORS.get(record.levelname, "")
        message = super().format(record)
        return f"{level_color}{message}{self.RESET}"


# ---------------------------------------------------------
# JSON log formatter (useful for containers / cloud logs)
# ---------------------------------------------------------
class JSONFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


# ---------------------------------------------------------
# Initialize global logging configuration
# ---------------------------------------------------------
_initialized = False

def init_logging(force: bool = False):
    """
    Initialize logging once for the whole application.
    Safe to call multiple times (does nothing after first init).
    """
    global _initialized
    if _initialized and not force:
        return

    logging.root.handlers.clear()

    # root logger
    logging.root.setLevel(LOG_LEVEL)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    if LOG_JSON:
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(ColorFormatter("[%(levelname)s] %(name)s: %(message)s"))

    logging.root.addHandler(console_handler)

    # Rotating file handler
    try:
        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=LOG_MAX_MB * 1024 * 1024,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8"
        )
        if LOG_JSON:
            file_handler.setFormatter(JSONFormatter())
        else:
            file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logging.root.addHandler(file_handler)
    except Exception as e:
        print("Failed to create log file handler:", e)

    _initialized = True


# ---------------------------------------------------------
# Helper to get named loggers
# ---------------------------------------------------------
def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with proper configuration.
    Ensures logging is initialized.
    """
    if not _initialized:
        init_logging()
    return logging.getLogger(name)


# ---------------------------------------------------------
# FastAPI request logging middleware
# ---------------------------------------------------------
async def fastapi_logging_middleware(request, call_next):
    """
    Logs each request and its response status code.
    Add this in FastAPI:
    
        from backend.app.utils.logging_utils import fastapi_logging_middleware
        app.middleware("http")(fastapi_logging_middleware)
    """
    logger = get_logger("rag_app.requests")
    logger.info(f"Incoming: {request.method} {request.url.path}")

    try:
        response = await call_next(request)
    except Exception as e:
        logger.error(f"Exception while processing {request.method} {request.url.path}: {e}", exc_info=True)
        raise

    logger.info(f"Completed {request.method} {request.url.path} -> {response.status_code}")
    return response
