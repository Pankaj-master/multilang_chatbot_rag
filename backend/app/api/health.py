# backend/app/api/health.py
from fastapi import APIRouter
from dotenv import load_dotenv
import os
import psycopg2

# Load .env
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env'))

router = APIRouter()

DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://postgres:postgres@localhost:5432/ragdb'
)

@router.get("/health")
def health():
    db_ok = False
    db_err = None

    # Check Postgres only
    try:
        conn = psycopg2.connect(DATABASE_URL, connect_timeout=3)
        conn.close()
        db_ok = True
    except Exception as e:
        db_err = str(e)

    # Redis removed — health depends only on DB
    result = {
        "ok": db_ok,
        "db": "up" if db_ok else "down"
    }

    if db_err:
        result["db_error"] = db_err

    return result
