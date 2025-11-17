import os
from datetime import datetime
import utils
import scraper
import model

today = datetime.today().strftime("%Y-%m-%d")
torvik_path = f"data/torvik{today}.json"
kenpom_path = f"data/kenpom{today}.json"
dataset_path = f"model_data/cbb_data.json"

# Update data if not done for today
if not os.path.exists(torvik_path):
    scraper.torvik(today)
    print(f"Scraped Torvik for: {today}")

if not os.path.exists(kenpom_path):
    scraper.kenpom(today)
    print(f"Scraped Kenpom for: {today}")

if not os.path.exists(dataset_path):
    model.initDataset()
    print(f"Saved dataset to json.")

data = utils.load_json_data(dataset_path)
    