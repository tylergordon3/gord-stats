import requests
import pandas as pd
from tqdm import tqdm
from io import StringIO

def scrape_injuries_all(year, start_week, end_week):
    if start_week < 1: start_week = 1
    if end_week > 18: end_week = 18
    
    injury_df = pd.DataFrame()
    total_size = end_week - start_week + 1
    with tqdm(total=total_size, desc="Scraping injuries") as pbar:
        for week in range(start_week, end_week+1):
            curr_df = scrape_injuries(year, week)
            injury_df = pd.concat([injury_df, curr_df])
            pbar.update(1)
    
    return injury_df


def scrape_injuries(year, week):
    # Player	Position	Injuries	Practice Status	Game Status
    web = f'https://www.nfl.com/injuries/league/{year}/reg{week}'
    resp = requests.get(web, timeout=10).text
    list = pd.read_html(StringIO(resp))
    df = pd.DataFrame()
    for team in list:
        df = pd.concat([df, team])
    df = df.reset_index(drop=True)
    df = df[df["Game Status"] == 'Out']
    df['Cleaned Name'] = df['Player'].str.split()
    df['Cleaned Name'] = df['Cleaned Name'].apply(lambda lst: lst.str.join('') if len(lst) < 2 else ''.join(lst[:2]))
    df['Week'] = week
    return df
    