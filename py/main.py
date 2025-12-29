import os, json
import model, scraper, utils, predictions, constants, kenpom_model
import generate_home
import pandas as pd
import scraper
from datetime import datetime, date
import numpy as np
from render import render_home as rh
import re
from pathlib import Path

start = datetime.now()
today = datetime.today().strftime("%Y-%m-%d")

# Men's Data Setup
torvik_path = utils.get_path(f"data/men/torvik/torvik{today}.json")
kenpom_path = utils.get_path(f"data/men/kenpom/kenpom{today}.json")
torvik_dataset_path = utils.get_path("model_data/cbb_data.json")
kenpom_dataset_path = utils.get_path("model_data/kenpom_all.json")

# Women's Data Setup
torvik_w_path = utils.get_path(f"data/women/torvik{today}.json")

torvik_w_dataset_path = utils.get_path("model_data_w/torvik_w_all.json")

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
save_model_w = 0
if save_model:
    torvik_df = utils.load_json_data(torvik_dataset_path)
    with open(utils.get_path("model_data/kenpom_all.json"), "r", encoding="utf-8") as f:
        data = json.load(f)
    kenpom_df = pd.DataFrame(data, columns=constants.kenpom)
    model.trainModelsAndSave(torvik_df, update_about, gender="M")
    print(f"Torvik Men's training took: {(datetime.now() - start).total_seconds()}")
    kenpom_model.trainModelsAndSave(kenpom_df)
    print(f"Kenpom Men's training took: {(datetime.now() - start).total_seconds()}")

if save_model_w:
    with open(
        utils.get_path("model_data_w/torvik_w_all.json"), "r", encoding="utf-8"
    ) as f:
        data = json.load(f)
    torvik_w_df = pd.DataFrame(data, columns=constants.torvik_women)

    torvik_w_df["TOURNEY"] = np.where(
        torvik_w_df["Tourney"].map({"True": True, "False": False}), True, False
    )
    model.trainModelsAndSave(torvik_w_df, update_about, gender="W")
    print(f"Torvik Women's training took: {(datetime.now() - start).total_seconds()}")

update_mens_all = 0
if update_mens_all:
    path = utils.get_path('data/men/kenpom/')
    files = os.listdir(path)
    files_strip = [x[6:-5] for x in files]
    date_lst = [datetime.strptime(x, "%Y-%m-%d").date() for x in files_strip]
    for day in sorted(date_lst):
       predictions.predict(day)

today_df = predictions.predict(date.today())
today_w_df = predictions.predict_w(date.today())

games = scraper.today_games(today_df, 'M')
generate_home.generate_home_about(games, 'M', False)

games_women = scraper.today_games(today_w_df, 'W')
generate_home.generate_home_about(games_women, 'W', False)

rh.render_home(today_df, games, today_w_df, games_women)


