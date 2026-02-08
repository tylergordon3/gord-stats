import os
import re
import utils

FOLDER = utils.get_path("data/women/")  # <-- change this

pattern = re.compile(r"torvik(\d{4}-\d{2}-\d{2})\.json$")

for filename in os.listdir(FOLDER):
    match = pattern.match(filename)
    if not match:
        continue

    date_str = match.group(1)
    old_path = os.path.join(FOLDER, filename)
    new_path = os.path.join(FOLDER, f"{date_str}.json")

    if os.path.exists(new_path):
        print(f"⚠️ Skipping (already exists): {new_path}")
        continue

    os.rename(old_path, new_path)
    print(f"✅ {filename} → {date_str}.json")

