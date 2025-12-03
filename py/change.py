'''
    Module to scrape html and track team change over time
'''
import utils
import pandas as pd
from datetime import date, timedelta
from bs4 import BeautifulSoup
from io import StringIO

def change():
    today = date.today()
    week_ago = today - timedelta(days=7)
    week_ago_path = utils.get_recent_html(week_ago)
    with open(week_ago_path) as fp:
            soup = BeautifulSoup(fp, 'html.parser')
    table = soup.find("table")
    df = pd.read_html(StringIO(table.prettify()))[0]
    df['vs Last Wk'] = df['Overall'].apply(lambda x: x.split()[0])
    return df[['Team', 'vs Last Wk']].copy()
