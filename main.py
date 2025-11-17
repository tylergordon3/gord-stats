import scraper
import os
from datetime import datetime

today = datetime.today().strftime("%Y-%m-%d")
torvik_path = f"data/torvik{today}.json"
kenpom_path = f"data/kenpom{today}.json"

# Update data if not done for today
if os.path.exists(torvik_path):
    print(f"{torvik_path} exists.")
else:
    scraper.torvik(today)
    print(f"Scraped Torvik for: {today}")

if os.path.exists(kenpom_path):
    print(f"{kenpom_path} exists.")
else:
    scraper.kenpom(today)
    print(f"Scraped Kenpom for: {today}")