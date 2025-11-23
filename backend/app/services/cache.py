# backend/app/services/cache.py
"""
Async Redis cache helper using redis.asyncio (redis-py modern API).

Provides:
 - init_cache() / close_cache() for lifecycle management
 - get/set helpers (string)
 - get_json / set_json (JSON encode/decode)
 - incr, ttl helpers
 - simple distributed lock context manager using SET NX + expire

This module exposes `redis_client` (None until init_cache() is called).
Call init_cache() at application startup and close_cache() at shutdown.
"""

from __future__ import annotations
import asyncio
import json
import logging
from typing import Any, Optional, AsyncGenerator
import time

from redis import asyncio as aioredis  # redis.asyncio
from .. import config

logger = logging.getLogger("rag_app.cache")

redis_client: Optional[aioredis.Redis] = None


async def init_cache() -> None:
    """
    Initialize global redis client (call from FastAPI startup).
    """
    global redis_client
    if redis_client is not None:
        logger.debug("Redis client already initialized.")
        return

    url = config.redis_url_for_env()
    try:
        redis_client = aioredis.from_url(
            url,
            decode_responses=False,  # we return bytes for raw get; wrappers below decode appropriately
            max_connections=config.REDIS_POOL_MAX,
        )
        # quick ping
        pong = await redis_client.ping()
        logger.info("Redis ping: %s (url=%s)", pong, url)
    except Exception as e:
        redis_client = None
        logger.exception("Failed to initialize Redis client: %s", e)
        raise


async def close_cache() -> None:
    """
    Close redis client (call from FastAPI shutdown).
    """
    global redis_client
    if redis_client is None:
        logger.debug("Redis client not initialized; nothing to close.")
        return
    try:
        await redis_client.close()
        # connection pools may require wait_closed()
        if hasattr(redis_client, "connection_pool") and getattr(redis_client.connection_pool, "disconnect", None):
            try:
                redis_client.connection_pool.disconnect()
            except Exception:
                pass
        logger.info("Redis client closed.")
    except Exception as e:
        logger.exception("Error closing Redis client: %s", e)
    finally:
        redis_client = None


# ------------- Basic helpers -------------
async def get(key: str) -> Optional[bytes]:
    """
    Return raw bytes for a key, or None.
    """
    if redis_client is None:
        raise RuntimeError("Redis client not initialized")
    val = await redis_client.get(key)
    return val


async def set(key: str, value: Any, expire_seconds: Optional[int] = None) -> bool:
    """
    Set value. If value is not bytes/str, it will be JSON-dumped.
    """
    if redis_client is None:
        raise RuntimeError("Redis client not initialized")
    # accept bytes / str / other -> store bytes
    if isinstance(value, bytes):
        store = value
    elif isinstance(value, str):
        store = value.encode("utf-8")
    else:
        store = json.dumps(value, ensure_ascii=False).encode("utf-8")
    if expire_seconds:
        res = await redis_client.set(key, store, ex=expire_seconds)
    else:
        res = await redis_client.set(key, store)
    return bool(res)


async def delete(key: str) -> int:
    """
    Delete key. Returns number of keys deleted.
    """
    if redis_client is None:
        raise RuntimeError("Redis client not initialized")
    return await redis_client.delete(key)


# ------------- JSON helpers -------------
async def get_json(key: str, default: Any = None) -> Any:
    """
    Get a JSON value (stored by set_json). Returns default if key missing.
    """
    raw = await get(key)
    if raw is None:
        return default
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        logger.exception("Failed to decode JSON from cache key=%s", key)
        return default


async def set_json(key: str, obj: Any, expire_seconds: Optional[int] = None) -> bool:
    """
    Store a Python object as JSON.
    """
    return await set(key, obj, expire_seconds=expire_seconds)


# ------------- Numeric helpers -------------
async def incr(key: str, amount: int = 1) -> int:
    """
    Increment a key atomically and return new value.
    """
    if redis_client is None:
        raise RuntimeError("Redis client not initialized")
    return await redis_client.incr(key, amount)


async def ttl(key: str) -> int:
    """
    Get TTL (seconds) for a key; -2 if missing, -1 if key exists with no TTL.
    """
    if redis_client is None:
        raise RuntimeError("Redis client not initialized")
    return await redis_client.ttl(key)


# ------------- Simple distributed lock (safe-ish) -------------
class RedisLock:
    """
    Simple async context manager for a Redis-based lock.
    Usage:
        async with RedisLock("mylock", expire=10):
            # critical section
    This uses SET NX with expire as decent primitive. Not as robust as Redlock for
    distributed critical sections, but OK for short-lived locks.
    """

    def __init__(self, name: str, timeout: int = 10, retry_delay: float = 0.1, max_retries: int = 50):
        self.name = f"lock:{name}"
        self.timeout = timeout
        self.retry_delay = retry_delay
        self.max_retries = max_retries
        self._token = f"{time.time()}-{id(self)}"

    async def acquire(self) -> bool:
        if redis_client is None:
            raise RuntimeError("Redis client not initialized")
        tries = 0
        while tries < self.max_retries:
            # SET name token NX EX timeout
            ok = await redis_client.set(self.name, self._token.encode("utf-8"), nx=True, ex=self.timeout)
            if ok:
                return True
            await asyncio.sleep(self.retry_delay)
            tries += 1
        return False

    async def release(self) -> bool:
        """
        Release only if token matches to avoid deleting another client's lock.
        Uses Lua script for atomic check-and-del.
        """
        if redis_client is None:
            raise RuntimeError("Redis client not initialized")
        lua = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        try:
            res = await redis_client.eval(lua, 1, self.name, self._token)
            return bool(res)
        except Exception:
            logger.exception("Failed to release lock %s", self.name)
            return False

    async def __aenter__(self):
        ok = await self.acquire()
        if not ok:
            raise TimeoutError(f"Failed to acquire redis lock {self.name}")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.release()


def get_lock(name: str, timeout: int = 10, retry_delay: float = 0.1, max_retries: int = 50) -> RedisLock:
    return RedisLock(name, timeout=timeout, retry_delay=retry_delay, max_retries=max_retries)
