from datetime import date
import os
import predictions

def update_html(dates):
    for day in dates:
        predictions.predict(day)

def generate_home_about():
    update = False

    today = date.today()
    path = '../docs/'
    all_entries = os.listdir(path)
    valid = []
    for filename in all_entries:
        if os.path.isfile(filename):
            ifdate = filename[8:-5]
            try: 
                get_date = date.fromisoformat(ifdate)
                valid.append(get_date)
            except:
                continue
    dates = sorted(valid)
    if update:
        update_html(dates)
    history = '../docs/history.html'
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
       print(f'Wrote to: {path} for {day}')

    recent = sorted(dates, reverse=True)[0]
    index = f'''
---
layout: default
title: Bracket Gordology
---
    <p><a href="about.html" title="About the Model">About the Model</a></p>
    <p><a href="tgordon_final.html" title="Original Project">Original Project</a></p>

    <p>Predictions as of now use Torvik and Kenpom data from 2013 to present.</p>
    <p><a href="predict_{recent}.html" title="Current Model">Current Model</a></p>
    <p><a href="history.html" title="Model History">Model History</a></p>
'''
    with open('../docs/index.html', 'w') as f: 
       f.write(index.lstrip())  
       print(f'Wrote to: {path} for {day}')
