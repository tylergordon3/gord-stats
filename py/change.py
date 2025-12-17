'''
    Module to scrape html and track team change over time
'''
import utils
import pandas as pd
from datetime import date, timedelta
from bs4 import BeautifulSoup
from io import StringIO

def change(date):
    week_ago = date - timedelta(days=7)
    week_ago_path = utils.get_recent_html(week_ago)
    today_path = utils.get_recent_html(date)
    with open(week_ago_path) as fp:
        soup = BeautifulSoup(fp, 'html.parser')
    table = soup.find("table")
    df = pd.read_html(StringIO(table.prettify()))[0]
    def getOvr(x):
        splt = x.split()
        return splt[0][1:]
    if today_path == week_ago_path:
        df['vs Last Wk'] = 'NR'
    else:
        df['vs Last Wk'] = df['Overall'].apply(lambda x: getOvr(x))
    return df[['Team', 'vs Last Wk']].copy()

def change_w(date):
    week_ago = date - timedelta(days=7)
    week_ago_path = utils.get_recent_html_w(week_ago)
    today_path = utils.get_recent_html_w(date)
    with open(week_ago_path) as fp:
        soup = BeautifulSoup(fp, 'html.parser')
    table = soup.find("table")
    df = pd.read_html(StringIO(table.prettify()))[0]
    def getOvr(x):
        splt = x.split()
        return splt[0][1:]
    if today_path == week_ago_path:
        df['vs Last Wk'] = 'NR'
    else:
        df['vs Last Wk'] = df['Overall'].apply(lambda x: getOvr(x))
    return df[['Team', 'vs Last Wk']].copy()
