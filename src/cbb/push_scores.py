import os

import requests
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
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=20,
    )

    if not res.ok:
        print("PUSH FAILED")
        print("Status:", res.status_code)
        print("Response:", res.text[:1000]) 
        res.raise_for_status()

    try:
        data = res.json()
        writes_today = data.get("meta", {}).get("kv_writes_today")
        if isinstance(writes_today, int):
            print(f"KV writes today: {writes_today}")
    except Exception:
        pass
