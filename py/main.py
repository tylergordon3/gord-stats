import os, json
import model, scraper, utils, predictions, constants
import pandas as pd
import scraper
from datetime import datetime, date
import numpy as np
from render import render_home as rh
from render import render_conferences as rc
import kenpom_model_api
import kenpom

start = datetime.now()
today = datetime.today().strftime("%Y-%m-%d")

# Men's Data Setup
torvik_path = utils.get_path(f"data/men/torvik/{today}.json")
kenpom_path = utils.get_path(f"data/men/kenpom_api/{today}.json")

torvik_dataset_path = utils.get_path("model_data/torvik/cbb_data.json")
kenpom_dataset_path = utils.get_path("model_data/kenpom_api/all.json")

# Women's Data Setup
torvik_w_path = utils.get_path(f"data/women/torvik/{today}.json")

torvik_w_dataset_path = utils.get_path("model_data_w/torvik_w_all.json")

# Update data if not done for today
if not os.path.exists(torvik_path):
    scraper.torvik(today)
    print(f"Scraped Torvik for: {today}")

if not os.path.exists(kenpom_path):
    kenpom.kenpom_now()
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
    model.trainModelsAndSave(torvik_df, update_about, gender="M")
    print(f"Torvik Men's training took: {(datetime.now() - start).total_seconds()}")
    kenpom_model_api.main()
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

update_mens_v2 = 0
if update_mens_v2:
    path = utils.get_path('data/men/kenpom_api/')
    files = os.listdir(path)
    files_strip = [x[:-5] for x in files]
    date_lst = [datetime.strptime(x, "%Y-%m-%d").date() for x in files_strip]
    for day in sorted(date_lst):
       predictions.predict(day)

update_womens_all = 1
if update_womens_all:
    path = utils.get_path('data/women/torvik')
    files = os.listdir(path)
    files_strip = [x[:-5] for x in files]
    date_lst = [datetime.strptime(x, "%Y-%m-%d").date() for x in files_strip]
    for day in sorted(date_lst):
       predictions.predict_w(day)

[today_df, main] = predictions.predict(date.today())
[today_w_df, main_w] = predictions.predict_w(date.today())

rc.main(main, 'M')
rc.main(main_w, 'W')

rh.render_home()


