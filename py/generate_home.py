from datetime import date
import predictions
import utils
import os
from os.path import exists
from pytz import timezone
import datetime

def update_html(dates):
    for day in dates:
        predictions.predict(day)

def generate_home_about(gamesToday, update=False):
    today = date.today()
    mypath = utils.get_path('docs/men/')
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
    history = utils.get_path('docs/men/men_history.html')
    html = f"""---
layout: default
title: History
---
"""
    for day in dates:
        if day < today:
            link = f'predict_{day}.html'
            title = f'Prediction - {day}'
            line = f'<p><a href="{link}" title="{title}">{title}</a></p>'
            html += line

    with open(history, 'w') as f: 
       f.write(html)  
       print(f'Wrote to: {mypath} for {today}')

    tz = timezone('EST')
    time_obj = datetime.datetime.now(tz)
    time = time_obj.strftime("Last Update: %A %m/%d/%y %I:%M %p")
    recent = sorted(dates, reverse=True)[0]
    index = f'''
---
layout: default
title: Bracket Gordology
---
    <p>Using machine learning to predict the NCAA March Madness field.</p>
    <p>Data Sources: <a href='https://kenpom.com/'>Kenpom</a> | <a href='https://barttorvik.com/#'>Torvik</a></p>
    <p>Today's scores and schedule from: <a href='https://www.cbssports.com/college-basketball/scoreboard/'>CBS Sports</a></p>
    <h3>Today's Games</h3>
    <p>{time}</p>
    {gamesToday}
'''
    with open(utils.get_path('docs/men/men_index.html'), 'w') as f: 
       f.write(index.lstrip())  
       print(f'Wrote to: {mypath} for {day}')
