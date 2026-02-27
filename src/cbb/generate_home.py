import datetime
import os
from datetime import date

from pytz import timezone

from cbb import predictions, utils


def update_html(dates):
    for day in dates:
        predictions.predict(day)


def generate_home_about(gamesToday, gender, update=False):
    if gender == "M":
        path = "docs/men/"
        gender_title = "Mens"
    elif gender == "W":
        path = "docs/women/"
        gender_title = "Womens"
    today = date.today()
    mypath = utils.get_path(path)
    all_entries = os.listdir(mypath)
    valid = []
    for filename in all_entries:
        filepath = os.path.join(mypath, filename)
        if os.path.isfile(filepath):
            ifdate = filename[8:-5]
            try:
                get_date = date.fromisoformat(ifdate)
                valid.append(get_date)
            except:
                continue
    dates = sorted(valid)
    if update:
        update_html(dates)
    hist_path = path + "history.html"
    history = utils.get_path(hist_path)
    html = f"""---
layout: default
title: History
---
"""
    for day in dates:
        if day < today:
            link = f"predict_{day}.html"
            title = f"Prediction - {day}"
            line = f'<p><a href="{link}" title="{title}">{title}</a></p>'
            html += line

    with open(history, "w") as f:
        f.write(html)
        print(f"Wrote to: {mypath} for {today}")

    tz = timezone("EST")
    time_obj = datetime.datetime.now(tz)
    time = time_obj.strftime("Last Update: %A %m/%d/%y %I:%M %p")
    recent = sorted(dates, reverse=True)[0]
    index = f"""
---
layout: default
title: Bracket Gordology
---
    <h3>Today's {gender_title} Games</h3>
    <p>{time}</p>
    {gamesToday}
"""
    save_path = path + "index.html"
    with open(utils.get_path(save_path), "w") as f:
        f.write(index.lstrip())
        print(f"Wrote to: {mypath} for {day}")
