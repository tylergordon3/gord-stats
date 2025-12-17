import os, json
import model, scraper, utils, predictions, constants, kenpom_model
import generate_home
import pandas as pd
import scraper
from datetime import datetime, date

start = datetime.now()
today = datetime.today().strftime("%Y-%m-%d")
torvik_path = utils.get_path(f"data/torvik{today}.json")
kenpom_path = utils.get_path(f"data/kenpom{today}.json")
torvik_dataset_path = utils.get_path("model_data/cbb_data.json")
kenpom_dataset_path = utils.get_path("model_data/kenpom_all.json")

torvik_w_path = utils.get_path(f"data_w/torvik_w{today}.json")
# Update data if not done for today
if not os.path.exists(torvik_path):
    scraper.torvik(today)
    print(f"Scraped Torvik for: {today}")

if not os.path.exists(kenpom_path):
    scraper.kenpom(today)
    print(f"Scraped Kenpom for: {today}")

if not os.path.exists(torvik_w_path):
    scraper.torvik_w(today)
    print(f"Scraped Women's Torvik for: {today}")

if not os.path.exists(torvik_dataset_path):
    model.initDataset()
    print(f"Saved dataset to json.")

if not os.path.exists(kenpom_dataset_path):
    scraper.kenpom_historic()
    print(f"Saved dataset to json.")

update_about = 0
save_model = 0
if save_model:
    torvik_df = utils.load_json_data(torvik_dataset_path)
    with open('model_data/kenpom_all.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    kenpom_df = pd.DataFrame(data, columns=constants.kenpom)
    model.trainModelsAndSave(torvik_df, update_about)
    print(f'Torvik training took: {(datetime.now() - start).total_seconds()}')
    kenpom_model.trainModelsAndSave(kenpom_df)
    print(f'Kenpom training took: {(datetime.now() - start).total_seconds()}')

today_df = predictions.predict(date.today())

games = scraper.today_games(today_df)
generate_home.generate_home_about(games, False)



