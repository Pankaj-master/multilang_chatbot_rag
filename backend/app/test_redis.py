import os
import redis

url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
print("Using REDIS_URL:", url)

try:
    r = redis.from_url(url)
    pong = r.ping()
    print("Redis ping:", pong)
    r.set("rag_test_key", "ok", ex=5)
    print("Redis set/get:", r.get("rag_test_key"))
    print("Redis connection: OK")
except Exception as e:
    print("Redis connection: FAILED")
    print(e)