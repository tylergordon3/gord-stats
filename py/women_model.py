import pandas as pd
from lib import paths
from datetime import datetime
import os
import json

# Load the HTML file

# Read all tables
hdr = [
    "Rank",
    "School",
    "Record",
    "Conf",
    "Road",
    "Neutral",
    "Home",
    "Non-Div I",
    "Prev",
    "Quad 1",
    "Quad 2",
    "Quad 3",
    "Quad 4",
]

cols = [
    "Team",
    "Conference",
    "12/01/2025 Result",
    "NET Rank",
    "Prev NET",
    "Avg Opp NET Rank",
    "Avg Opp NET",
    "Wins",
    "Div I WL",
    "Wins.1",
    "Conf Record",
    "Wins.2",
    "Non-Conf Record",
    "Wins.3",
    "Road WL",
    "NET SOS",
    "Net NonConf SOS",
    "WAB Rk",
    "WAB",
    "NC WAB Rk",
    "NC WAB",
    "Wins.4",
    "Last 10 Games",
    "Wins.5",
    "Q1",
    "Wins.6",
    "Q2",
    "Wins.7",
    "Q3",
    "Wins.8",
    "Q4",
]

for filename in os.listdir(paths.W_NET_DIR):

    if filename[-5:] == ".html":
        file_path = os.path.join(paths.W_NET_DIR, filename)
        df = pd.read_html(file_path)[0]
        if len(df) > 3:
            df = df[
                [
                    "NET Rank",
                    "Team",
                    "Conference",
                    "Div I WL",
                    "Road WL",
                    "Prev NET",
                    "Q1",
                    "Q2",
                    "Q3",
                    "Q4",
                ]
            ].copy()
            df = df.rename(
                columns={
                    "NET Rank": "Rank",
                    "Team": "School",
                    "Conference": "Conf",
                    "Div I WL": "Record",
                    "Road WL": "Road",
                    "Prev": "Prev NET",
                    "Q1": "Quad 1",
                    "Q2": "Quad 2",
                    "Q3": "Quad 3",
                    "Q4": "Quad 4",
                }
            )

            base = os.path.splitext(filename)[0]
            date_obj = datetime.strptime(base, "%Y%m%d")
            formatted = date_obj.strftime("%Y-%m-%d") + ".json"
            save = paths.W_NET_DIR / formatted 

            payload = {
                "headers": list(df.columns),
                "rows": df.values.tolist(),
            }
            with open(save, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=4)
