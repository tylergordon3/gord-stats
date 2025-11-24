import os
import model, scraper, utils, predictions
from datetime import datetime, date

today = datetime.today().strftime("%Y-%m-%d")
torvik_path = utils.get_path(f"data/torvik{today}.json")
kenpom_path = utils.get_path(f"data/kenpom{today}.json")
dataset_path = utils.get_path("model_data/cbb_data.json")
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

update_about = 0
save_model = 0
if save_model:
    df = utils.load_json_data(dataset_path)
    model.trainModelsAndSave(df, update_about)

predictions.predict(date.today())
    