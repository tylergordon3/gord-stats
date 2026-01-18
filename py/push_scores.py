import requests
import json
import os

WORKER_INGEST = "https://cbb-live-scores.tmgordon33.workers.dev/ingest"
INGEST_KEY = os.environ.get("INGEST_KEY")

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

    print("✅ PUSH OK")
