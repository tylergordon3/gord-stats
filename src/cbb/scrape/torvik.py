"""
Bart Torvik's T-Rank tables, men's and women's, for the bracketology models.

Built from two files Torvik publishes as plain CSV: `{season}_team_results.csv`
(ratings, record, tempo, WAB) and `{season}_fffinal.csv` (the four factors).
Joined on the team, they are the 24 columns of his main table that the models
were trained on. That table sits behind a "Verifying your browser" check only
a real browser clears, which is why this module drove Chromium through
Playwright - and why, when that broke in March 2026, it was commented out of
daily_data and the Torvik and women's models kept scoring March's file.

Written to the same {"headers", "rows"} JSON as the scrape was, so nothing
downstream changes.
"""
import io
import json
import warnings
from datetime import datetime

import pandas as pd
import requests

from cbb import utils
from cbb import paths

_BASE = {"M": "https://barttorvik.com", "W": "https://barttorvik.com/ncaaw"}
_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/126 Safari/537.36"}
_TIMEOUT = 30

# The main table's columns, in its order, and where each comes from.
HEADERS = ["Rk", "Team", "Conf", "G", "Rec", "AdjOE", "AdjDE", "Barthag", "EFG%", "EFGD%",
           "TOR", "TORD", "ORB", "DRB", "FTR", "FTRD", "2P%", "2P%D", "3P%", "3P%D",
           "3PR", "3PRD", "Adj T.", "WAB"]
_RESULTS = {"Rk": "rank", "Team": "team", "Conf": "conf", "Rec": "record",
            "AdjOE": "adjoe", "AdjDE": "adjde", "Barthag": "barthag", "Adj T.": "adjt",
            "WAB": "WAB"}
# DRB on the main table is the offensive rebound rate a team ALLOWS (lower is
# better), which is what fffinal calls DR% - checked against the March scrape.
_FACTORS = {"EFG%": "eFG%", "EFGD%": "eFG% Def", "TOR": "TO%", "TORD": "TO% Def.",
            "ORB": "OR%", "DRB": "DR%", "FTR": "FTR", "FTRD": "FTR Def",
            "2P%": "2p%", "2P%D": "2p%D", "3P%": "3P%", "3P%D": "3pD%",
            "3PR": "3P rate", "3PRD": "3P rate D"}

def get_today_tor(gender="M"):
    if gender == "M":
        dir = paths.M_TOR_DIR
    elif gender == "W":
        dir = paths.W_TOR_DIR
    
     # Today's filename
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_file = dir / f"{today_str}.json"

    # If today's file exists, return it
    if today_file.exists():
        target_file = today_file

    # Otherwise get most recent file
    files = sorted(
        dir.glob("*.json"),
        key=lambda f: f.name,
        reverse=True,
    )

    if not files:
        return None

    target_file = files[0]

    # Load JSON
    with open(target_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data

def _csv(url: str) -> pd.DataFrame:
    r = requests.get(url, headers=_UA, timeout=_TIMEOUT)
    r.raise_for_status()
    if "csv" not in (r.headers.get("content-type") or ""):
        # The browser check answers 200 with an HTML page, so a status test
        # alone would read "Verifying your browser" as an empty season.
        raise RuntimeError(f"{url} did not return a CSV (behind Torvik's browser check, "
                           "or not published for this season yet)")
    # fffinal's rows carry more fields than its header names. Left alone, pandas
    # turns the leading columns into an index and everything shifts; this keeps
    # the header aligned from the left and drops the unnamed tail.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", pd.errors.ParserWarning)
        return pd.read_csv(io.StringIO(r.text), index_col=False)


def table(gender: str, season: int) -> dict:
    """{"headers", "rows"}: the season's T-Rank table for "M" or "W"."""
    base = _BASE[gender]
    results = _csv(f"{base}/{season}_team_results.csv")
    factors = _csv(f"{base}/{season}_fffinal.csv")
    merged = results.merge(factors, left_on="team", right_on="TeamName", how="inner")
    # A name the two files spell differently drops a team from the field. A
    # couple is tolerable; losing a meaningful share is a changed format.
    if len(merged) < 0.97 * len(results):
        raise RuntimeError(f"Torvik's two {gender} files matched only {len(merged)} of "
                           f"{len(results)} teams")
    out = pd.DataFrame({h: merged[c] for h, c in {**_RESULTS, **_FACTORS}.items()})
    wl = out["Rec"].astype(str).str.extract(r"(\d+)-(\d+)").astype(float)
    out["G"] = (wl[0] + wl[1]).fillna(0).astype(int)
    out = out.sort_values("Rk")[HEADERS]
    return {"headers": HEADERS, "rows": out.astype(str).values.tolist()}


def _write(directory, gender: str, date: str) -> None:
    data = table(gender, utils.season_year(date))
    utils.save_json_data(data, directory / f"{date}.json")


def mens_tor(date):
    _write(paths.M_TOR_DIR, "M", date)


def womens_tor(date):
    _write(paths.W_TOR_DIR, "W", date)
