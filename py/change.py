'''
    Module to scrape html and track team change over time
'''
import utils
import pandas as pd
from datetime import timedelta, date
from bs4 import BeautifulSoup
from io import StringIO

def change(date):
    today_path = utils.get_recent_html(date)

    delta7 = date - timedelta(days=7)
    delta7_path = utils.get_recent_html(delta7)
    
    delta14 = date - timedelta(days=14)
    delta14_path = utils.get_recent_html(delta14)
    
    delta30 = date - timedelta(days=30)
    delta30_path = utils.get_recent_html(delta30)

    def getOvr(x):
        splt = x.split()
        return splt[0][1:]
    
    def calc_delta(path, label):
        with open(path) as fp:
            soup = BeautifulSoup(fp, 'html.parser')
        table = soup.find("table")
        df = pd.read_html(StringIO(table.prettify()))[0]

        if today_path == path:
            df[label] = 'NR'
        else:
            df[label] = df['Ovr'].apply(lambda x: getOvr(x))
        df['Team'] = df["Team"].str.replace(r"\s*\([^)]*\)", "", regex=True)
        return df[['Team', label]].copy()
    
    df7 = calc_delta(delta7_path, "Δ 7d")
    df14 = calc_delta(delta14_path, "Δ 14d")
    dfm = calc_delta(delta30_path, "Δ 1mo")
    
    df = pd.merge(df7, df14, "left", "Team")
    df = pd.merge(df, dfm, "left", "Team")
    
    return df

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
        df['Last Wk'] = 'NR'
    else:
        df['Last Wk'] = df['Ovr'].apply(lambda x: getOvr(x))
    return df[['Team', 'Last Wk']].copy()
