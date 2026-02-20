import json
from pathlib import Path

def load_json_data(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)