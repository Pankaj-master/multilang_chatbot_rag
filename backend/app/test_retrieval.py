# backend/app/test_retrieval.py (replace payload and call)
import requests, json, time

API = "http://localhost:8001/chat"
payload = {
  "message": "Summarize the document I just uploaded",
  "user_language": "en"
}

print("Waiting 2s for indexing...")
time.sleep(2)
r = requests.post(API, json=payload, timeout=120)
print("status:", r.status_code)
try:
    print(json.dumps(r.json(), indent=2, ensure_ascii=False))
except Exception:
    print("non-json response:", r.text)
