import os
from datetime import date, datetime

from cbb import daily_data, predictions, utils
from cbb.render import render_conferences as rc
from cbb.render import render_home as rh
from cbb.wnba import wnba_remaining

start = datetime.now()
today = datetime.today().strftime("%Y-%m-%d")

# daily_data.get_data()

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

#[today_df, main] = predictions.predict(date.today())
#[today_w_df, main_w] = predictions.predict_womens(date.today())

#rc.main(main, 'M')
#rc.main(main_w, 'W')
wnba_remaining.wnba_update()
rh.render_home()


