import requests
import os
from dotenv import load_dotenv

load_dotenv() 

WORKER_INGEST = "https://cbb-live-scores.tmgordon33.workers.dev/ingest"
INGEST_KEY = os.getenv("INGEST_KEY")

def push(payload):
    if not INGEST_KEY:
        raise RuntimeError("INGEST_KEY not set")
    res = requests.post(
        WORKER_INGEST,
        headers={
            "Authorization": f"Bearer {INGEST_KEY}",
            "Content-Type": "application/json"
        },
        json=payload,          # 👈 important (see below)
        timeout=20
    )

    if not res.ok:
        print("❌ PUSH FAILED")
        print("Status:", res.status_code)
        print("Response:", res.text[:1000])  # truncate
        res.raise_for_status()

      # ---- optional: log KV writes from Worker ----
    try:
        data = res.json()
        writes_today = data.get("meta", {}).get("kv_writes_today")
        if isinstance(writes_today, int):
            print(f"🧮 KV writes today: {writes_today}")
    except Exception:
        # ignore non-JSON or missing meta
        pass