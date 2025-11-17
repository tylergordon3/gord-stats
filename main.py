import os
from datetime import datetime
import utils
import scraper
import model
from io import StringIO
import pandas as pd

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
df = pd.read_json(StringIO(data))

update_about = 0
model.run(df, update_about)
    