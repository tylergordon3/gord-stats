"""
Module to scrape html and track team change over time
"""

import pandas as pd
import scraper
from datetime import timedelta


def closest_date(dates, target):
    return min(dates, key=lambda d: abs(d - target))


def change(date, gender="M"):
    delta1 = date - timedelta(days=1)
    delta7 = date - timedelta(days=7)
    delta14 = date - timedelta(days=14)
    delta30 = date - timedelta(days=30)
    if gender == "W":
        ranks = scraper.getWTeamRanks()
    else:
        ranks = scraper.getTeamRanks()
    keys = ranks.keys()
    date_keys = [date.fromisoformat(k) for k in keys]

    d1 = closest_date(date_keys, delta1)
    d7 = closest_date(date_keys, delta7)
    d14 = closest_date(date_keys, delta14)
    d30 = closest_date(date_keys, delta30)

    def extract_ovr(data):
        return {team: info["Ovr"] for team, info in data.items() if "Ovr" in info}

    d1_dict = extract_ovr(ranks[d1.isoformat()])
    d7_dict = extract_ovr(ranks[d7.isoformat()])
    d14_dict = extract_ovr(ranks[d14.isoformat()])
    d30_dict = extract_ovr(ranks[d30.isoformat()])
    today = extract_ovr(ranks[date.isoformat()])

    df = pd.DataFrame([today])
    df = pd.concat([df, pd.DataFrame([d1_dict])])
    df = pd.concat([df, pd.DataFrame([d7_dict])])
    df = pd.concat([df, pd.DataFrame([d14_dict])])
    df = pd.concat([df, pd.DataFrame([d30_dict])])
    df.index = ["Today", "1day", "7day", "14day", "30day"]
    df = df.T
    df["delt1"] = df.apply(lambda x: x["1day"] - x["Today"], axis=1)
    df["delt7"] = df.apply(lambda x: x["7day"] - x["Today"], axis=1)
    df["delt14"] = df.apply(lambda x: x["14day"] - x["Today"], axis=1)
    df["delt30"] = df.apply(lambda x: x["30day"] - x["Today"], axis=1)

    df = df.drop(columns=["Today", "1day", "7day", "14day", "30day"])
    df = df.rename(
        columns={"delt1": "Δ 1d", "delt7": "Δ 7d", "delt14": "Δ 14d", "delt30": "Δ 1mo"}
    )
    df = df.reset_index(names=["Team"])
    return df
