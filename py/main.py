import os, json
import model, scraper, utils, predictions, constants
import pandas as pd
import scraper
from datetime import datetime, date
import numpy as np
from render import render_home as rh
from render import render_conferences as rc
import daily_data

start = datetime.now()
today = datetime.today().strftime("%Y-%m-%d")

daily_data.get_data()

update_mens = 0
if update_mens:
    path = utils.get_path('data/men/kenpom_api/')
    files = os.listdir(path)
    files_strip = [x[:-5] for x in files]
    date_lst = [datetime.strptime(x, "%Y-%m-%d").date() for x in files_strip]
    for day in sorted(date_lst):
       predictions.predict(day)

update_womens_all = 0
if update_womens_all:
    path = utils.get_path('data/women/torvik')
    files = os.listdir(path)
    files_strip = [x[:-5] for x in files]
    date_lst = [datetime.strptime(x, "%Y-%m-%d").date() for x in files_strip]
    for day in sorted(date_lst):
       predictions.predict_womens(day)

[today_df, main] = predictions.predict(date.today())
[today_w_df, main_w] = predictions.predict_womens(date.today())

rc.main(main, 'M')
rc.main(main_w, 'W')

rh.render_home()


